"""
Rendering Widget
UI for texture rendering and playback module.
"""

import sys
import ctypes
import time
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QSlider, QLabel,
    QCheckBox, QComboBox, QSpinBox, QPlainTextEdit, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
import numpy as np
import pyqtgraph as pg
from processing.rendering import (
    Renderer,
    PlaybackController,
    boundary_crossfade_gains,
    make_boundary_crossfade_loop,
)
from processing.recording import Recording


REFILL_INTERVAL_S = 0.003
SPIN_WAIT_S = 0.0005
PREFILL_SAMPLES = 128
TARGET_FILL_SAMPLES = 1024
MAX_FILL_SAMPLES = 2048
MAX_TOPUP_SAMPLES = 128


class WindowsTimerResolution:
    """Temporarily request 1 ms Windows scheduler timer resolution."""

    def __init__(self, milliseconds: int = 1):
        self.milliseconds = int(milliseconds)
        self._enabled = False
        self._winmm = None

    def __enter__(self):
        if sys.platform.startswith("win"):
            try:
                self._winmm = ctypes.WinDLL("winmm")
                if self._winmm.timeBeginPeriod(self.milliseconds) == 0:
                    self._enabled = True
            except Exception:
                self._enabled = False
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._enabled and self._winmm is not None:
            try:
                self._winmm.timeEndPeriod(self.milliseconds)
            except Exception:
                pass
        self._enabled = False


def precise_wait_until(deadline: float) -> None:
    """Sleep cooperatively until a high-resolution monotonic deadline."""
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0.0:
            return
        if remaining > SPIN_WAIT_S:
            time.sleep(max(0.0, remaining - SPIN_WAIT_S))
        else:
            time.sleep(0)


class DevicePlaybackWorker(QThread):
    """Feed rendered samples to the haptic device at the playback rate."""

    error = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(
        self,
        hardware_interface,
        signal_data: np.ndarray,
        sample_rate: int,
        output_channels: list[int],
        loop: bool = False,
        boundary_window: str = "full_hann_50",
        crossfade_ms: float = 20.0,
    ):
        super().__init__()
        self.hardware_interface = hardware_interface
        self.signal_data = np.asarray(signal_data, dtype=np.float32).reshape(-1)
        self.sample_rate = int(sample_rate)
        self.output_channels = output_channels or [1]
        self.loop = bool(loop)
        if self.loop:
            self.signal_data = make_boundary_crossfade_loop(
                self.signal_data,
                self.sample_rate,
                crossfade_ms,
                boundary_window,
            )

    def run(self):
        rendering_started = False
        start_time = None
        sent = 0
        try:
            if len(self.signal_data) == 0:
                raise ValueError("Cannot play an empty signal")

            if hasattr(self.hardware_interface, "configure_render_timing"):
                self.hardware_interface.configure_render_timing(self.sample_rate)
            elif hasattr(self.hardware_interface, "send_command"):
                self.hardware_interface.send_command("CONFIG_STREAM", self.sample_rate, "")

            if hasattr(self.hardware_interface, "configure_render_outputs"):
                self.hardware_interface.configure_render_outputs(self.output_channels)
            elif hasattr(self.hardware_interface, "configure_channel"):
                for channel in self.output_channels:
                    self.hardware_interface.configure_channel(channel, role="output", stream_enabled=False)

            chunk_samples = max(1, int(getattr(self.hardware_interface, "_render_frame_samples", 32)))

            def send_samples(sample_count: int) -> int:
                nonlocal sent
                written = 0
                while written < sample_count and not self.isInterruptionRequested():
                    absolute_position = sent + written
                    signal_offset = absolute_position % len(self.signal_data)
                    write_count = min(chunk_samples, sample_count - written)
                    signal_end = signal_offset + write_count
                    if signal_end <= len(self.signal_data):
                        block = self.signal_data[signal_offset:signal_end]
                    elif self.loop:
                        wrap_count = signal_end - len(self.signal_data)
                        block = np.concatenate(
                            (self.signal_data[signal_offset:], self.signal_data[:wrap_count])
                        )
                    else:
                        block = self.signal_data[signal_offset:]
                    if len(block) == 0:
                        break
                    self.hardware_interface.write_render_buffer(
                        block
                    )
                    written += len(block)
                    progress_samples = (
                        (sent + written) % len(self.signal_data)
                        if self.loop
                        else sent + written
                    )
                    self.progress.emit(int(100 * progress_samples / max(1, len(self.signal_data))))
                    if not self.loop and absolute_position + len(block) >= len(self.signal_data):
                        break
                sent += written
                return written

            prefill = min(
                PREFILL_SAMPLES,
                len(self.signal_data) if not self.loop else PREFILL_SAMPLES,
            )
            target_fill = min(
                TARGET_FILL_SAMPLES,
                len(self.signal_data) if not self.loop else TARGET_FILL_SAMPLES,
            )
            max_fill = min(
                MAX_FILL_SAMPLES,
                len(self.signal_data) if not self.loop else MAX_FILL_SAMPLES,
            )

            # The firmware retains samples queued before START_RENDER.
            send_samples(prefill)
            if self.isInterruptionRequested():
                return

            self.hardware_interface.start_rendering()
            rendering_started = True
            start_time = time.perf_counter()
            next_refill_time = start_time

            with WindowsTimerResolution(1):
                while (
                    (self.loop or sent < len(self.signal_data))
                    and not self.isInterruptionRequested()
                ):
                    now = time.perf_counter()
                    elapsed = now - start_time
                    target_sent = int(elapsed * max(1, self.sample_rate)) + target_fill
                    max_sent = int(elapsed * max(1, self.sample_rate)) + max_fill
                    if not self.loop:
                        target_sent = min(target_sent, len(self.signal_data))
                        max_sent = min(max_sent, len(self.signal_data))
                    if target_sent > sent:
                        samples_to_send = min(MAX_TOPUP_SAMPLES, max_sent - sent)
                        if samples_to_send > 0:
                            send_samples(samples_to_send)

                    next_refill_time += REFILL_INTERVAL_S
                    if next_refill_time < time.perf_counter():
                        next_refill_time = time.perf_counter() + REFILL_INTERVAL_S
                    precise_wait_until(next_refill_time)

            # On natural completion, let the device consume its queued tail
            # before STOP_RENDER clears the render ring.
            if not self.loop and not self.isInterruptionRequested() and start_time is not None:
                elapsed_samples = int((time.perf_counter() - start_time) * self.sample_rate)
                queued_samples = max(0, sent - elapsed_samples)
                drain_time = min(3.0, queued_samples / max(1, self.sample_rate) + 0.1)
                if drain_time > 0.0:
                    precise_wait_until(time.perf_counter() + drain_time)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if rendering_started:
                try:
                    self.hardware_interface.stop_rendering()
                except Exception:
                    pass


class RenderingWidget(QWidget):
    """Widget for rendering and playback module."""
    
    playback_started = pyqtSignal()
    playback_stopped = pyqtSignal()
    
    def __init__(self, sample_rate: int = 10000, hardware_interface=None):
        super().__init__()
        self.sample_rate = sample_rate
        self.hardware_interface = hardware_interface
        self.renderer = Renderer(sample_rate)
        self.playback_controller = PlaybackController(sample_rate)
        self.current_recording = None
        self.current_model = None
        self.current_characterization = None
        self.current_compensation = None
        self._imu_monitor_running = False
        self.device_playback_worker = None
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI elements."""
        layout = QVBoxLayout()
        layout.setSpacing(14)
        
        # Configuration
        config_group = QGroupBox("What will be played")
        config_layout = QVBoxLayout()
        config_layout.setSpacing(10)
        
        self.now_playing_label = QLabel("No texture prepared")
        self.now_playing_label.setWordWrap(True)
        self.now_playing_label.setMinimumHeight(56)
        self.now_playing_label.setStyleSheet(
            "QLabel { background: #eaf7fd; color: #16324d; border: 1px solid #0aa9e8; "
            "border-radius: 7px; padding: 12px 16px; font-size: 17px; }"
        )
        config_layout.addWidget(self.now_playing_label)

        details_layout = QHBoxLayout()
        details_layout.addWidget(QLabel("Source:"))
        self.model_label = QLabel("No recording")
        self.model_label.setStyleSheet("font-weight: 600;")
        details_layout.addWidget(self.model_label)
        details_layout.addSpacing(24)
        details_layout.addWidget(QLabel("Compensation:"))
        self.compensation_name = QLabel("None")
        self.compensation_name.setStyleSheet("font-weight: 600;")
        details_layout.addWidget(self.compensation_name)
        details_layout.addStretch()
        config_layout.addLayout(details_layout)

        output_group = QGroupBox("Choose workshop output")
        output_layout = QHBoxLayout()
        output_layout.setSpacing(18)
        self.output_channel_checks = []
        workshop_outputs = [
            ("Output 1", "Haptuator"),
            ("Output 2", "LRA"),
        ]
        for channel, (output_name, actuator_name) in enumerate(workshop_outputs):
            check = QCheckBox(f"{output_name}\n{actuator_name}")
            check.setChecked(channel == 0)
            check.setMinimumHeight(70)
            check.setStyleSheet(
                "QCheckBox { font-size: 17px; font-weight: 600; padding: 12px 18px; "
                "background: #ffffff; color: #263246; border: 1px solid #cbd5e1; border-radius: 7px; }"
                "QCheckBox:hover { background: #eaf7fd; border-color: #0aa9e8; }"
                "QCheckBox::indicator { width: 24px; height: 24px; }"
            )
            check.toggled.connect(self._update_now_playing)
            self.output_channel_checks.append(check)
            output_layout.addWidget(check, 1)
        output_group.setLayout(output_layout)
        config_layout.addWidget(output_group)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # Playback controls
        playback_group = QGroupBox("Playback")
        playback_layout = QVBoxLayout()
        playback_layout.setSpacing(14)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        playback_button_style = (
            "QPushButton { min-height: 54px; min-width: 145px; border-radius: 7px; "
            "font-size: 18px; font-weight: 600; padding: 4px 18px; }"
        )
        self.play_button = QPushButton("▶  Play")
        self.play_button.setStyleSheet(
            playback_button_style
            + "QPushButton { background: #073f83; color: white; border: 2px solid #073f83; }"
            "QPushButton:hover { background: #09539f; border-color: #0aa9e8; }"
            "QPushButton:disabled { background: #dbe2ec; color: #8a96a8; border-color: #d3d9e3; }"
        )
        self.play_button.clicked.connect(self.start_playback)
        button_layout.addWidget(self.play_button)
        
        self.pause_button = QPushButton("Ⅱ  Pause")
        self.pause_button.setStyleSheet(
            playback_button_style
            + "QPushButton { background: #0aa9e8; color: #07304f; border: 2px solid #0aa9e8; }"
            "QPushButton:hover { background: #35bbed; border-color: #073f83; }"
            "QPushButton:disabled { background: #dbe2ec; color: #8a96a8; border-color: #d3d9e3; }"
        )
        self.pause_button.clicked.connect(self.pause_playback)
        self.pause_button.setEnabled(False)
        button_layout.addWidget(self.pause_button)
        
        self.stop_button = QPushButton("■  Stop")
        self.stop_button.setStyleSheet(
            playback_button_style
            + "QPushButton { background: white; color: #073f83; border: 2px solid #073f83; }"
            "QPushButton:hover { background: #eaf7fd; border-color: #0aa9e8; }"
            "QPushButton:disabled { background: #f2f4f7; color: #a3adbb; border-color: #d3d9e3; }"
        )
        self.stop_button.clicked.connect(self.stop_playback)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)
        
        self.loop_check = QCheckBox("↻  Keep playing (loop)")
        self.loop_check.setMinimumHeight(54)
        self.loop_check.setStyleSheet(
            "QCheckBox { font-size: 17px; font-weight: 600; padding: 8px 14px; "
            "background: #ffffff; color: #263246; border: 1px solid #cbd5e1; border-radius: 7px; }"
            "QCheckBox::indicator { width: 24px; height: 24px; }"
            "QCheckBox:checked { background: #eaf7fd; border-color: #0aa9e8; }"
        )
        self.loop_check.toggled.connect(self._update_loop_controls)
        button_layout.addWidget(self.loop_check)
        
        button_layout.addStretch()
        playback_layout.addLayout(button_layout)

        self.windowing_group = QGroupBox("Loop windowing")
        self.windowing_group.setStyleSheet(
            "QGroupBox:disabled { color: #9aa3b2; border-color: #d9dee7; }"
            "QLabel:disabled { color: #9aa3b2; }"
            "QComboBox:disabled, QSpinBox:disabled {"
            "  background-color: #e5e7eb;"
            "  color: #9aa3b2;"
            "  border: 1px solid #cbd1da;"
            "}"
            "QComboBox:disabled::drop-down, QSpinBox:disabled::up-button,"
            "QSpinBox:disabled::down-button {"
            "  background-color: #d9dee7;"
            "  border-color: #cbd1da;"
            "}"
            "QComboBox:enabled, QSpinBox:enabled {"
            "  background-color: #ffffff;"
            "  color: #263246;"
            "  border: 1px solid #aeb8c6;"
            "}"
            "QComboBox:enabled::drop-down, QSpinBox:enabled::up-button,"
            "QSpinBox:enabled::down-button {"
            "  background-color: #f4f7fa;"
            "  border-color: #aeb8c6;"
            "}"
        )
        windowing_layout = QVBoxLayout()
        crossfade_layout = QHBoxLayout()
        crossfade_layout.addWidget(QLabel("Loop boundary:"))
        self.boundary_window_combo = QComboBox()
        self.boundary_window_combo.addItem("Off (hard repeat)", "off")
        self.boundary_window_combo.addItem("Full Hann · 50% overlap", "full_hann_50")
        self.boundary_window_combo.addItem("Half-Hann / Tukey edge", "half_hann")
        self.boundary_window_combo.addItem("Linear", "linear")
        self.boundary_window_combo.addItem("Smoothstep", "smoothstep")
        self.boundary_window_combo.addItem("Smootherstep", "smootherstep")
        self.boundary_window_combo.addItem("Equal-power sine", "equal_power")
        self.boundary_window_combo.setCurrentIndex(1)
        self.boundary_window_combo.currentIndexChanged.connect(self._update_window_plot)
        crossfade_layout.addWidget(self.boundary_window_combo)
        crossfade_layout.addSpacing(18)
        crossfade_layout.addWidget(QLabel("Crossfade:"))
        self.crossfade_duration_spin = QSpinBox()
        self.crossfade_duration_spin.setRange(1, 100)
        self.crossfade_duration_spin.setValue(20)
        self.crossfade_duration_spin.setSuffix(" ms")
        self.crossfade_duration_spin.valueChanged.connect(self._update_window_plot)
        crossfade_layout.addWidget(self.crossfade_duration_spin)
        crossfade_layout.addStretch()
        windowing_layout.addLayout(crossfade_layout)

        self.window_plot = pg.PlotWidget()
        self.window_plot.setBackground("#ffffff")
        self.window_plot.setLabel("left", "Gain")
        self.window_plot.setLabel("bottom", "Boundary time", units="ms")
        self.window_plot.setTitle("Loop-boundary crossfade")
        self.window_plot.setMinimumHeight(150)
        self.window_plot.setMaximumHeight(190)
        self.window_plot.showGrid(x=True, y=True, alpha=0.25)
        self.window_plot.addLegend(offset=(10, 10))
        windowing_layout.addWidget(self.window_plot)
        self.windowing_group.setLayout(windowing_layout)
        playback_layout.addWidget(self.windowing_group)
        self._update_loop_controls(False)
        
        # Volume control
        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("Volume (dB):"))
        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setMinimum(-40)
        self.volume_slider.setMaximum(20)
        self.volume_slider.setValue(-24)
        self.volume_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        volume_layout.addWidget(self.volume_slider)
        
        self.volume_label = QLabel("-24 dB")
        widest_db_text = max(
            ("-40 dB", "+20 dB"),
            key=self.volume_label.fontMetrics().horizontalAdvance,
        )
        self.volume_label.setFixedWidth(
            self.volume_label.fontMetrics().horizontalAdvance(widest_db_text) + 12
        )
        self.volume_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        volume_layout.addWidget(self.volume_label)
        playback_layout.addLayout(volume_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        playback_layout.addWidget(self.progress_bar)
        
        playback_group.setLayout(playback_layout)
        layout.addWidget(playback_group)
        
        # Output signal
        monitor_group = QGroupBox("Output Signal")
        monitor_layout = QVBoxLayout()
        
        button_layout = QHBoxLayout()
        self.render_button = QPushButton("Prepare Signal")
        self.render_button.clicked.connect(self.prepare_signal)
        button_layout.addWidget(self.render_button)
        
        button_layout.addStretch()
        monitor_layout.addLayout(button_layout)

        self.waveform_plot = pg.PlotWidget()
        self.waveform_plot.setBackground("#ffffff")
        self.waveform_plot.setLabel("left", "Amplitude")
        self.waveform_plot.setLabel("bottom", "Time", units="s")
        self.waveform_plot.setTitle("Rendered Time Signal")
        self.waveform_plot.showGrid(x=True, y=True, alpha=0.3)
        self.waveform_plot.setMinimumHeight(150)
        self.waveform_plot.getPlotItem().getAxis("left").setPen(pg.mkPen(color="#617086", width=1))
        self.waveform_plot.getPlotItem().getAxis("bottom").setPen(pg.mkPen(color="#617086", width=1))
        self.waveform_plot.getPlotItem().getAxis("left").setTextPen("#263246")
        self.waveform_plot.getPlotItem().getAxis("bottom").setTextPen("#263246")
        signal_layout = QHBoxLayout()
        signal_layout.addWidget(self.waveform_plot, stretch=3)
        
        # Info display
        self.info_text = QPlainTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMinimumWidth(150)
        self.info_text.setMaximumWidth(320)
        signal_layout.addWidget(self.info_text, stretch=1)
        monitor_layout.addLayout(signal_layout)
        
        monitor_group.setLayout(monitor_layout)
        layout.addWidget(monitor_group)
        
        # Status display
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()
        
        self.status_text = QPlainTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(80)
        status_layout.addWidget(self.status_text)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # Timer for playback status updates
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_playback_status)
    
    def set_recording(self, recording: Recording):
        """Set current recording for rendering."""
        self.current_recording = recording
        if self.current_model is None:
            self.model_label.setText("Recorded texture")
        self._update_now_playing()

    def set_model(self, model: dict):
        """Set the texture model selected in the Texture Model tab."""
        self.current_model = model
        model_type = model.get("model_type", "Recorded texture") if model else "Recorded texture"
        self.model_label.setText(model_type)
        self._update_now_playing()
    
    def set_characterization(self, characterization):
        """Set actuator characterization."""
        self.current_characterization = characterization
    
    def set_compensation(self, compensation):
        """Set compensation filter."""
        self.current_compensation = compensation
        self.compensation_name.setText(
            getattr(compensation, "name", "")
            or getattr(compensation, "actuator_name", "")
            or "None"
            if compensation
            else "None"
        )
        self._update_now_playing()
    
    def prepare_signal(self):
        """Prepare the final signal and show it in the time domain."""
        if not self.current_recording:
            self.status_text.setPlainText("No recording loaded")
            return
        
        try:
            rendered = self._render_pipeline_signal()
            
            # Load into playback
            self.playback_controller.load_texture(rendered)
            self._show_time_signal(rendered)
            self._update_window_plot()
            
            # Update info
            info_text = f"Rendered: {len(rendered)} samples ({len(rendered)/self.sample_rate:.2f}s)\n"
            info_text += f"RMS Level: {np.sqrt(np.mean(rendered**2)):.3f}\n"
            info_text += f"Peak Level: {np.max(np.abs(rendered)):.3f}\n"
            info_text += f"Output channels: {', '.join(str(channel) for channel in self.selected_output_channels())}"
            
            self.info_text.setPlainText(info_text)
            self.play_button.setEnabled(True)
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(False)
            self.status_text.setPlainText("Ready for playback")
            self._update_now_playing()
        except Exception as e:
            self.status_text.setPlainText(f"Error: {str(e)}")

    def _update_now_playing(self):
        if not hasattr(self, "now_playing_label"):
            return
        data = self.playback_controller.playback_data
        if data is None:
            source = self.model_label.text() if hasattr(self, "model_label") else "texture"
            self.now_playing_label.setText(f"{source} — press “Prepare Signal” before playing")
            return
        duration = len(data) / max(1, self.sample_rate)
        outputs = []
        for index, check in enumerate(self.output_channel_checks):
            if check.isChecked():
                outputs.append(f"Output {index + 1}")
        output_text = " + ".join(outputs) if outputs else "Output 2"
        source = self.model_label.text()
        self.now_playing_label.setText(
            f"{source}  •  {duration:.1f} seconds  •  {self.sample_rate / 1000:g} ksample/s"
            f"\nPlaying through {output_text}"
        )

    def _show_time_signal(self, signal_data: np.ndarray):
        """Plot the prepared output signal against time."""
        self.waveform_plot.clear()
        if signal_data is None or len(signal_data) == 0:
            return
        data = np.asarray(signal_data, dtype=np.float32).reshape(-1)
        if len(data) > 10000:
            step = int(np.ceil(len(data) / 10000))
            plot_data = data[::step]
            plot_time = np.arange(0, len(data), step, dtype=np.float64) / max(1, self.sample_rate)
        else:
            plot_data = data
            plot_time = np.arange(len(data), dtype=np.float64) / max(1, self.sample_rate)
        self.waveform_plot.plot(
            plot_time[: len(plot_data)],
            plot_data,
            pen=pg.mkPen(color="#0aa9e8", width=1.8),
        )

    def _render_pipeline_signal(self) -> np.ndarray:
        """Render from the selected upstream texture model and compensation."""
        if self.current_model and "reconstructed" in self.current_model:
            rendered = np.asarray(self.current_model["reconstructed"], dtype=np.float32).reshape(-1)
        else:
            data = np.asarray(self.current_recording.data, dtype=np.float32)
            rendered = data[:, 0] if data.ndim > 1 else data

        if self.current_compensation is not None:
            rendered = self.renderer.compensator.apply(rendered, self.current_compensation)

        gain_linear = 10 ** (self.volume_slider.value() / 20)
        return np.clip(rendered * gain_linear, -1.0, 1.0)
    
    def start_playback(self):
        """Start playback."""
        if self.playback_controller.playback_data is None:
            self.prepare_signal()
        if self.playback_controller.playback_data is None:
            return
        
        self.playback_controller.set_loop(self.loop_check.isChecked())
        self.playback_controller.start()
        self._start_device_playback()
        
        self.play_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_text.setPlainText("Playback: PLAYING")
        
        self.status_timer.start(100)
        self.playback_started.emit()
    
    def pause_playback(self):
        """Pause playback."""
        self.playback_controller.pause()
        
        self.play_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.status_text.setPlainText("Playback: PAUSED")
    
    def stop_playback(self):
        """Stop playback."""
        self.playback_controller.stop()
        self._stop_device_playback()
        
        self.play_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        self.status_text.setPlainText("Playback: STOPPED")
        
        self.status_timer.stop()
        self.playback_stopped.emit()
    
    def on_volume_changed(self):
        """Handle volume slider change."""
        db = self.volume_slider.value()
        self.volume_label.setText(f"{db} dB")
        if self.playback_controller.playback_data is not None:
            self.playback_controller.set_gain(db)
    
    def update_playback_status(self):
        """Update playback status display."""
        if self.playback_controller.is_playing:
            progress = self.progress_bar.value()
            total = len(self.playback_controller.playback_data) if self.playback_controller.playback_data is not None else 0
            time_s = (progress / 100.0) * (total / self.sample_rate) if self.sample_rate > 0 else 0
            self.status_text.setPlainText(f"Playback: {progress}% ({time_s:.2f}s)")

    def _start_device_playback(self):
        if not self.hardware_interface or not hasattr(self.hardware_interface, "write_render_buffer"):
            return
        self._stop_device_playback()
        self.device_playback_worker = DevicePlaybackWorker(
            self.hardware_interface,
            self.playback_controller.playback_data,
            self.sample_rate,
            self.selected_output_channels(),
            self.loop_check.isChecked(),
            self.boundary_window_combo.currentData(),
            self.crossfade_duration_spin.value(),
        )
        self.device_playback_worker.error.connect(self._on_device_playback_error)
        self.device_playback_worker.progress.connect(self.progress_bar.setValue)
        self.device_playback_worker.finished.connect(self._on_device_playback_finished)
        self.device_playback_worker.start()

    def _stop_device_playback(self):
        if self.device_playback_worker and self.device_playback_worker.isRunning():
            self.device_playback_worker.requestInterruption()
            self.device_playback_worker.wait(1000)
        self.device_playback_worker = None

    def _on_device_playback_error(self, error: str):
        self.status_text.setPlainText(f"Device playback failed: {error}")

    def _on_device_playback_finished(self):
        if self.playback_controller.is_playing:
            self.playback_controller.stop()
            self.play_button.setEnabled(True)
            self.pause_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.progress_bar.setVisible(False)
            self.progress_bar.setValue(100)
            self.status_timer.stop()
            self.status_text.setPlainText("Playback: FINISHED")
            self.playback_stopped.emit()

    def selected_output_channels(self) -> list[int]:
        channels = [index for index, check in enumerate(self.output_channel_checks) if check.isChecked()]
        return channels or [1]

    def _configure_render_outputs(self):
        if not self.hardware_interface:
            return
        channels = self.selected_output_channels()
        if hasattr(self.hardware_interface, "configure_render_outputs"):
            self.hardware_interface.configure_render_outputs(channels)
        elif hasattr(self.hardware_interface, "configure_channel"):
            for channel in channels:
                self.hardware_interface.configure_channel(channel, role="output", stream_enabled=False)

    def _update_loop_controls(self, enabled: bool):
        """Enable boundary controls for looping and refresh their preview."""
        self.windowing_group.setEnabled(enabled)
        self.crossfade_duration_spin.setEnabled(
            enabled
            and self.boundary_window_combo.currentData() not in ("off", "full_hann_50")
        )
        self.window_plot.setBackground("#ffffff" if enabled else "#eef1f5")
        self.window_plot.getPlotItem().setOpacity(1.0 if enabled else 0.35)
        self._update_window_plot()

    def _update_window_plot(self):
        """Plot three complete signal windows and their collaborative gain."""
        if not hasattr(self, "window_plot"):
            return
        self.window_plot.clear()
        window_type = self.boundary_window_combo.currentData()
        enabled = self.loop_check.isChecked()
        self.crossfade_duration_spin.setEnabled(
            enabled and window_type not in ("off", "full_hann_50")
        )
        data = self.playback_controller.playback_data
        signal_duration = (
            len(data) / max(1, self.sample_rate)
            if data is not None and len(data) > 0
            else 0.4
        )
        overlap = (
            signal_duration / 2.0
            if window_type == "full_hann_50"
            else min(
                self.crossfade_duration_spin.value() / 1000.0,
                signal_duration / 2.0,
            )
        )
        hop = signal_duration if window_type == "off" else signal_duration - overlap
        starts = (-hop, 0.0, hop)
        timeline = np.linspace(starts[0], starts[-1] + signal_duration, 1600)

        def signal_envelope(start: float) -> np.ndarray:
            local_time = timeline - start
            inside = (local_time >= 0.0) & (local_time < signal_duration)
            envelope = np.zeros_like(timeline)
            if not np.any(inside):
                return envelope
            phase = local_time[inside] / signal_duration
            if window_type == "off":
                envelope[inside] = 1.0
            elif window_type == "full_hann_50":
                envelope[inside] = 0.5 - 0.5 * np.cos(2.0 * np.pi * phase)
            else:
                taper_points = 500
                fade_out, fade_in = boundary_crossfade_gains(taper_points, window_type)
                taper_phase = np.linspace(0.0, 1.0, taper_points, endpoint=False)
                values = np.ones(np.count_nonzero(inside), dtype=np.float64)
                local_inside = local_time[inside]
                fade_in_region = local_inside < overlap
                fade_out_region = local_inside >= signal_duration - overlap
                values[fade_in_region] = np.interp(
                    local_inside[fade_in_region] / overlap,
                    taper_phase,
                    fade_in,
                )
                values[fade_out_region] = np.interp(
                    (local_inside[fade_out_region] - (signal_duration - overlap)) / overlap,
                    taper_phase,
                    fade_out,
                )
                envelope[inside] = values
            return envelope

        envelopes = [signal_envelope(start) for start in starts]
        colors = ("#8fd3ee", "#0aa9e8", "#f28e2b")
        names = ("Previous signal", "Current signal", "Next signal")
        time_ms = timeline * 1000.0
        for envelope, color, name in zip(envelopes, colors, names):
            self.window_plot.plot(
                time_ms,
                envelope,
                pen=pg.mkPen(color, width=2.1),
                name=name,
            )
        self.window_plot.plot(
            time_ms,
            np.sum(envelopes, axis=0),
            pen=pg.mkPen("#2f7d32", width=2.7, style=Qt.PenStyle.DashLine),
            name="Collaborative gain",
        )
        self.window_plot.setLabel("bottom", "Signal timeline", units="ms")
        label = self.boundary_window_combo.currentText()
        detail = (
            "50% overlap"
            if window_type == "full_hann_50"
            else "hard repeat"
            if window_type == "off"
            else f"{overlap * 1000.0:g} ms overlap"
        )
        self.window_plot.setTitle(
            f"{label} · {signal_duration * 1000.0:g} ms signals · {detail}"
        )
        self.window_plot.setYRange(0.0, 1.5, padding=0.02)
