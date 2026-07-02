"""
Recording Widget
UI for recording module.
"""

import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
    QLabel, QTextEdit, QProgressBar, QFileDialog, QMessageBox, QInputDialog,
    QCheckBox, QGridLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
import numpy as np
from processing.recording import Recording, RecordingMetadata
from data import FileIO
from ui.recording_display_widget import RecordingDisplayWidget
from hardware.imu_config import max_rate_for_fields
import time

class RecordingWorker(QThread):
    """Worker thread for non-blocking recording."""
    
    progress = pyqtSignal(int)
    live_data = pyqtSignal(object, int, list, int)  # data, sample_rate, channel_names, first sample index
    finished = pyqtSignal(np.ndarray, int, list, float, dict)  # data, sample_rate, channel_names, elapsed_s, timing
    error = pyqtSignal(str, dict)
    LIVE_PREVIEW_MAX_SAMPLES = 100_000
    
    IMU_FIELD_PATHS = {
        "accel_x": ("accel", 0),
        "accel_y": ("accel", 1),
        "accel_z": ("accel", 2),
        "gyro_x": ("gyro", 0),
        "gyro_y": ("gyro", 1),
        "gyro_z": ("gyro", 2),
        "mag_x": ("mag", 0),
        "mag_y": ("mag", 1),
        "mag_z": ("mag", 2),
        "pressure": ("bmp_pressure_raw", None),
        "temperature": ("bmp_temperature_raw", None),
    }

    def __init__(
        self,
        duration: float,
        sample_rate: int,
        recording_interface,
        pixi_channels: list[int],
        imu_fields: list[str],
        imu_sample_rate: int,
    ):
        super().__init__()
        self.duration = duration
        self.sample_rate = sample_rate
        self.recording_interface = recording_interface
        self.pixi_channels = pixi_channels
        self.imu_fields = imu_fields
        self.imu_sample_rate = imu_sample_rate
    
    def run(self):
        """Run recording in thread."""
        num_samples = int(self.duration * self.sample_rate)
        pixi_chunks = []
        imu_samples = []
        samples_read = 0
        setup_start_time = time.monotonic()
        acquisition_start_time = None
        lead_time = 0.0
        read_durations = []
        empty_reads = 0
        daq_samples_read = 0
        try:
            chunk_size = max(128, min(2048, self.sample_rate // 20))

            if self.pixi_channels:
                self.recording_interface.configure_channels(self.pixi_channels, self.sample_rate)
            if self.imu_fields and hasattr(self.recording_interface, "configure_imu_stream"):
                self.recording_interface.configure_imu_stream(
                    self.imu_sample_rate, True, self.imu_fields
                )
            self.recording_interface.start_acquisition()
            acquisition_start_time = time.monotonic()
            lead_time = acquisition_start_time - setup_start_time

            while samples_read < num_samples:
                if self.isInterruptionRequested():
                    break

                if self.imu_fields and hasattr(self.recording_interface, "read_available_imu"):
                    imu_samples.extend(self.recording_interface.read_available_imu(128))

                if self.pixi_channels:
                    wanted = min(chunk_size, num_samples - samples_read)
                    read_start_time = time.monotonic()
                    try:
                        chunk = self.recording_interface.read_data(wanted)
                    finally:
                        read_elapsed = time.monotonic() - read_start_time
                        read_durations.append(read_elapsed)
                    if chunk.ndim == 1:
                        chunk = chunk.reshape(-1, 1)
                    if len(chunk) == 0:
                        empty_reads += 1
                        time.sleep(0.01)
                        continue

                    pixi_chunks.append(chunk)
                    samples_read += len(chunk)
                    daq_samples_read += len(chunk)
                else:
                    time.sleep(0.02)
                    samples_read = min(num_samples, int((time.monotonic() - acquisition_start_time) * self.sample_rate))

                if self.imu_fields and hasattr(self.recording_interface, "read_available_imu"):
                    imu_samples.extend(self.recording_interface.read_available_imu(128))

                if samples_read == 0:
                    time.sleep(0.01)
                    continue
                preview, channel_names, first_sample = self._build_live_preview(
                    pixi_chunks, imu_samples, samples_read
                )
                self.live_data.emit(preview, self.sample_rate, channel_names, first_sample)
                self.progress.emit(min(100, int(100 * samples_read / num_samples)))

            acquisition_end_time = time.monotonic()
            self.recording_interface.stop_acquisition()
            if self.imu_fields and hasattr(self.recording_interface, "configure_imu_stream"):
                self.recording_interface.configure_imu_stream(self.imu_sample_rate, False)

            elapsed = acquisition_end_time - acquisition_start_time
            timing = self._build_timing_info(
                lead_time,
                elapsed,
                read_durations,
                empty_reads,
                daq_samples_read,
            )
            data, channel_names = self._build_recording(pixi_chunks, imu_samples, num_samples)
            self.finished.emit(data, self.sample_rate, channel_names, elapsed, timing)
        except Exception as e:
            acquisition_elapsed = time.monotonic() - acquisition_start_time if acquisition_start_time else 0.0
            timing = self._build_timing_info(
                lead_time,
                acquisition_elapsed,
                read_durations,
                empty_reads,
                daq_samples_read,
            )
            timing["partial_samples"] = samples_read
            timing["requested_samples"] = num_samples
            try:
                self.recording_interface.stop_acquisition()
            except Exception:
                pass
            if self.imu_fields and hasattr(self.recording_interface, "configure_imu_stream"):
                try:
                    self.recording_interface.configure_imu_stream(self.imu_sample_rate, False)
                except Exception:
                    pass
            self.error.emit(str(e), timing)

    def _build_timing_info(
        self,
        lead_time: float,
        acquisition_elapsed: float,
        read_durations: list[float],
        empty_reads: int,
        daq_samples_read: int,
    ) -> dict:
        read_count = len(read_durations)
        total_read_time = sum(read_durations)
        return {
            "lead_time": lead_time,
            "acquisition_elapsed": acquisition_elapsed,
            "read_count": read_count,
            "empty_reads": empty_reads,
            "total_read_time": total_read_time,
            "avg_read_time": total_read_time / read_count if read_count else 0.0,
            "max_read_time": max(read_durations) if read_durations else 0.0,
            "daq_samples_read": daq_samples_read,
            "daq_effective_rate": daq_samples_read / total_read_time if total_read_time > 0 else 0.0,
        }

    def _build_recording(self, pixi_chunks: list[np.ndarray], imu_samples: list[dict], num_samples: int) -> tuple[np.ndarray, list[str]]:
        columns = []
        channel_names = []

        if self.pixi_channels:
            if pixi_chunks:
                pixi_data = np.concatenate(pixi_chunks, axis=0)[:num_samples]
                if len(pixi_data) < num_samples:
                    pixi_data = np.pad(pixi_data, ((0, num_samples - len(pixi_data)), (0, 0)))
            else:
                pixi_data = np.zeros((num_samples, len(self.pixi_channels)))
            columns.append(pixi_data)
            channel_names.extend([f"Pixi {channel}" for channel in self.pixi_channels])

        for field in self.imu_fields:
            columns.append(self._imu_field_to_column(imu_samples, field, num_samples).reshape(-1, 1))
            channel_names.append(self._imu_channel_name(field))

        if not columns:
            return np.zeros(num_samples), ["Input 1"]

        data = np.hstack(columns)
        if data.shape[1] == 1:
            return data[:, 0], channel_names
        return data, channel_names

    def _build_live_preview(
        self,
        pixi_chunks: list[np.ndarray],
        imu_samples: list[dict],
        samples_read: int,
    ) -> tuple[np.ndarray, list[str], int]:
        """Build a bounded, time-aligned preview for the UI."""
        preview_samples = min(samples_read, self.LIVE_PREVIEW_MAX_SAMPLES)
        first_sample = max(0, samples_read - preview_samples)
        columns = []
        channel_names = []

        if self.pixi_channels:
            remaining = preview_samples
            recent_chunks = []
            for chunk in reversed(pixi_chunks):
                if remaining <= 0:
                    break
                take = min(remaining, len(chunk))
                recent_chunks.append(chunk[-take:])
                remaining -= take
            recent_chunks.reverse()
            pixi_data = np.concatenate(recent_chunks, axis=0) if recent_chunks else np.empty((0, len(self.pixi_channels)))
            if len(pixi_data) < preview_samples:
                pixi_data = np.pad(pixi_data, ((preview_samples - len(pixi_data), 0), (0, 0)))
            columns.append(pixi_data)
            channel_names.extend([f"Pixi {channel}" for channel in self.pixi_channels])

        target_time = np.arange(first_sample, samples_read, dtype=np.float64) / self.sample_rate
        for field in self.imu_fields:
            if imu_samples:
                values = np.asarray(
                    [self._extract_imu_value(sample, field) for sample in imu_samples],
                    dtype=np.float32,
                )
                timestamps = np.asarray(
                    [sample.get("timestamp_us", 0) for sample in imu_samples],
                    dtype=np.float64,
                ) / 1_000_000.0
                timestamps -= timestamps[0]
                if len(values) == 1 or np.all(timestamps == timestamps[0]):
                    imu_column = np.full(preview_samples, values[-1], dtype=np.float32)
                else:
                    imu_column = np.interp(
                        target_time, timestamps, values, left=values[0], right=values[-1]
                    ).astype(np.float32)
            else:
                imu_column = np.zeros(preview_samples, dtype=np.float32)
            columns.append(imu_column.reshape(-1, 1))
            channel_names.append(self._imu_channel_name(field))

        data = np.hstack(columns)
        if data.shape[1] == 1:
            data = data[:, 0]
        return data, channel_names, first_sample

    def _imu_field_to_column(self, imu_samples: list[dict], field: str, num_samples: int) -> np.ndarray:
        if not imu_samples:
            return np.zeros(num_samples)

        values = np.asarray([self._extract_imu_value(sample, field) for sample in imu_samples], dtype=np.float32)
        timestamps = np.asarray([sample.get("timestamp_us", 0) for sample in imu_samples], dtype=np.float64) / 1_000_000.0
        if len(values) == 1 or np.all(timestamps == timestamps[0]):
            return np.full(num_samples, values[-1], dtype=np.float32)
        timestamps -= timestamps[0]
        target_time = np.arange(num_samples, dtype=np.float64) / self.sample_rate
        return np.interp(target_time, timestamps, values, left=values[0], right=values[-1]).astype(np.float32)

    def _extract_imu_value(self, sample: dict, field: str) -> float:
        key, index = self.IMU_FIELD_PATHS[field]
        value = sample.get(key, 0)
        if index is None:
            return float(value)
        return float(value[index]) if len(value) > index else 0.0

    @staticmethod
    def _imu_channel_name(field: str) -> str:
        name = f"IMU {field.replace('_', ' ').title()}"
        return f"{name} (g)" if field.startswith("accel_") else name


class RecordingWidget(QWidget):
    """Widget for recording module."""
    
    recording_complete = pyqtSignal(Recording)
    
    def __init__(self, recording_interface):
        super().__init__()
        self.recording_interface = recording_interface
        self.recording_worker = None
        self.current_recording = None  # Store recording for saving
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI elements."""
        layout = QVBoxLayout()
        
        # Add display widget
        self.display_widget = RecordingDisplayWidget()
        layout.addWidget(self.display_widget)
        
        # Recording parameters
        params_group = QGroupBox("Recording Parameters")
        params_layout = QVBoxLayout()
        
        # Sample rate
        rate_layout = QHBoxLayout()
        rate_layout.addWidget(QLabel("Sample Rate (Hz):"))
        self.sample_rate_spinbox = QSpinBox()
        self.sample_rate_spinbox.setMinimum(1000)
        self.sample_rate_spinbox.setMaximum(192000)
        self.sample_rate_spinbox.setValue(10000)
        self.sample_rate_spinbox.setSingleStep(1000)
        rate_layout.addWidget(self.sample_rate_spinbox)
        rate_layout.addStretch()
        params_layout.addLayout(rate_layout)
        
        # Duration
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("Duration (s):"))
        self.duration_spinbox = QDoubleSpinBox()
        self.duration_spinbox.setMinimum(0.1)
        self.duration_spinbox.setMaximum(600.0)
        self.duration_spinbox.setValue(5.0)
        self.duration_spinbox.setSingleStep(0.1)
        duration_layout.addWidget(self.duration_spinbox)
        duration_layout.addStretch()
        params_layout.addLayout(duration_layout)

        # Input selection
        input_layout = QHBoxLayout()

        pixi_group = QGroupBox("Pixi Inputs")
        pixi_layout = QVBoxLayout()
        pixi_count_layout = QHBoxLayout()
        pixi_count_layout.addWidget(QLabel("Amount:"))
        self.pixi_input_count_spinbox = QSpinBox()
        self.pixi_input_count_spinbox.setRange(0, 20)
        self.pixi_input_count_spinbox.setValue(1)
        self.pixi_input_count_spinbox.valueChanged.connect(self.update_pixi_channel_checks)
        pixi_count_layout.addWidget(self.pixi_input_count_spinbox)
        pixi_count_layout.addStretch()
        pixi_layout.addLayout(pixi_count_layout)

        pixi_grid = QGridLayout()
        self.pixi_channel_checks = []
        for channel in range(20):
            check = QCheckBox(str(channel))
            check.setChecked(channel == 0)
            check.toggled.connect(self.update_pixi_input_count)
            self.pixi_channel_checks.append(check)
            pixi_grid.addWidget(check, channel // 10, channel % 10)
        pixi_layout.addLayout(pixi_grid)
        pixi_group.setLayout(pixi_layout)
        input_layout.addWidget(pixi_group)

        imu_group = QGroupBox("IMU Inputs")
        imu_layout = QVBoxLayout()
        imu_rate_layout = QHBoxLayout()
        imu_rate_layout.addWidget(QLabel("Rate (Hz):"))
        self.imu_rate_spinbox = QSpinBox()
        self.imu_rate_spinbox.setRange(1, 3200)
        self.imu_rate_spinbox.setSingleStep(1000)
        self.imu_rate_spinbox.setValue(100)
        imu_rate_layout.addWidget(self.imu_rate_spinbox)
        imu_rate_layout.addStretch()
        imu_layout.addLayout(imu_rate_layout)

        imu_grid = QGridLayout()
        self.imu_field_checks = {}
        imu_fields = [
            ("accel_x", "Accel X (g)"),
            ("accel_y", "Accel Y (g)"),
            ("accel_z", "Accel Z (g)"),
            ("gyro_x", "Gyro X"),
            ("gyro_y", "Gyro Y"),
            ("gyro_z", "Gyro Z"),
            ("mag_x", "Mag X"),
            ("mag_y", "Mag Y"),
            ("mag_z", "Mag Z"),
            ("pressure", "Pressure"),
            ("temperature", "Temperature"),
        ]
        for index, (field, label) in enumerate(imu_fields):
            check = QCheckBox(label)
            check.toggled.connect(self.update_imu_rate_limit)
            self.imu_field_checks[field] = check
            imu_grid.addWidget(check, index // 3, index % 3)
        imu_layout.addLayout(imu_grid)
        imu_group.setLayout(imu_layout)
        input_layout.addWidget(imu_group)
        self.update_imu_rate_limit()

        params_layout.addLayout(input_layout)
        
        params_group.setLayout(params_layout)
        layout.addWidget(params_group)
        
        # Control buttons
        control_layout = QHBoxLayout()
        
        self.record_button = QPushButton("▶ Start Recording")
        self.record_button.clicked.connect(self.start_recording)
        control_layout.addWidget(self.record_button)
        
        self.stop_button = QPushButton("⏹ Stop Recording")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_recording)
        control_layout.addWidget(self.stop_button)
        
        self.save_button = QPushButton("💾 Save Recording")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_recording)
        control_layout.addWidget(self.save_button)
        
        self.load_button = QPushButton("📁 Load Recording")
        self.load_button.clicked.connect(self.load_recording)
        control_layout.addWidget(self.load_button)
        
        layout.addLayout(control_layout)

        # Timing label
        self.timing_label = QLabel("Elapsed: \u2014")
        self.timing_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.timing_label.setWordWrap(True)
        layout.addWidget(self.timing_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        layout.addStretch()
        self.setLayout(layout)
    
    def start_recording(self):
        """Start recording."""
        self.record_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        duration = self.duration_spinbox.value()
        sample_rate = self.sample_rate_spinbox.value()
        pixi_channels = self.selected_pixi_channels()
        imu_fields = self.selected_imu_fields()

        if not pixi_channels and not imu_fields:
            QMessageBox.warning(self, "No Inputs", "Select at least one Pixi or IMU input.")
            self.record_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setVisible(False)
            return
        self.current_recording = None
        self.save_button.setEnabled(False)
        self.timing_label.setText("Elapsed: — / expected: %.2f s" % self.duration_spinbox.value())
        self.timing_label.setStyleSheet("")
        self.display_widget.clear_display()
        self._record_start_time = time.monotonic()
        
        self.recording_worker = RecordingWorker(
            duration,
            sample_rate,
            self.recording_interface,
            pixi_channels,
            imu_fields,
            self.imu_rate_spinbox.value(),
        )
        self.recording_worker.progress.connect(self.on_recording_progress)
        self.recording_worker.live_data.connect(self.on_live_data)
        self.recording_worker.finished.connect(self.on_recording_finished)
        self.recording_worker.error.connect(self.on_recording_error)
        self.recording_worker.start()
    
    def stop_recording(self):
        """Stop recording."""
        if self.recording_worker:
            self.recording_worker.requestInterruption()
            self.recording_worker.wait()
        
        self.record_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)
    
    def on_recording_progress(self, progress: int):
        """Update progress bar."""
        self.progress_bar.setValue(progress)

    def on_live_data(self, data: np.ndarray, sample_rate: int, channel_names: list, first_sample: int):
        """Update the waveform while samples are arriving."""
        self.display_widget.update_live_data(data, sample_rate, channel_names, first_sample)
    
    def on_recording_finished(self, data: np.ndarray, sample_rate: int, channel_names: list, elapsed: float, timing: dict):
        """Handle recording completion."""
        expected = len(data) / sample_rate if sample_rate else elapsed
        overrun = elapsed > expected * 1.05  # >5 % slower than expected
        colour = "color: red; font-weight: bold;" if overrun else "color: green;"
        self.timing_label.setText(
            f"Elapsed: {elapsed:.3f} s / expected: {expected:.3f} s"
            + ("  ⚠ overrun" if overrun else "")
            + self._format_daq_timing(timing)
        )
        self.timing_label.setStyleSheet(colour)

        metadata = RecordingMetadata(channel_names=channel_names)
        recording = Recording(data, sample_rate, metadata)
        self.current_recording = recording  # Store for saving
        self.recording_complete.emit(recording)
        
        # Update display with new recording
        self.display_widget.update_display(recording)
        
        self.record_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.save_button.setEnabled(True)  # Enable save button after recording
        self.progress_bar.setVisible(False)

    def _format_daq_timing(self, timing: dict) -> str:
        """Format acquisition lead time and DAQ read timing diagnostics."""
        if not timing:
            return ""
        read_count = int(timing.get("read_count", 0))
        if read_count == 0:
            return f" | lead: {timing.get('lead_time', 0.0) * 1000:.1f} ms | DAQ reads: none"
        return (
            f" | lead: {timing.get('lead_time', 0.0) * 1000:.1f} ms"
            f" | DAQ reads: {read_count}"
            f" | avg/max: {timing.get('avg_read_time', 0.0) * 1000:.1f}/{timing.get('max_read_time', 0.0) * 1000:.1f} ms"
            f" | empty: {int(timing.get('empty_reads', 0))}"
            f" | read rate: {timing.get('daq_effective_rate', 0.0):.0f} sps"
        )
    
    def on_recording_error(self, error: str, timing: dict):
        """Handle recording error."""
        print(f"Recording error: {error}")
        partial = ""
        if timing:
            partial = (
                f" | partial: {int(timing.get('partial_samples', 0))}/"
                f"{int(timing.get('requested_samples', 0))} samples"
                + self._format_daq_timing(timing)
            )
        self.timing_label.setText(f"Recording error: {error}{partial}")
        self.timing_label.setStyleSheet("color: red;")
        self.record_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)
    
    def save_recording(self):
        """Save current recording to file."""
        if not self.current_recording:
            QMessageBox.warning(self, "No Recording", "No recording to save. Record first.")
            return
        
        # Open file dialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Recording",
            "",
            "WAV Files (*.wav);;CSV Files (*.csv);;NPZ Files (*.npz)"
        )
        
        if not file_path:
            return
        
        try:
            file_io = FileIO()
            if file_path.endswith('.wav'):
                file_io.save_recording(file_path, self.current_recording, "wav")
            elif file_path.endswith('.csv'):
                file_io.save_recording(file_path, self.current_recording, "csv")
            elif file_path.endswith('.npz'):
                file_io.save_recording(file_path, self.current_recording, "npz")
            
            QMessageBox.information(self, "Success", f"Recording saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save recording:\n{str(e)}")
    
    def load_recording(self):
        """Load recording from file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Recording",
            "",
            "Recording Files (*.wav *.csv *.npz);;WAV Files (*.wav);;CSV Files (*.csv);;NPZ Files (*.npz)"
        )
        
        if not file_path:
            return
        
        try:
            file_io = FileIO()
            
            if file_path.endswith('.npz'):
                recording = file_io.load_recording(file_path, "npz")
            elif file_path.endswith('.wav'):
                recording = file_io.load_recording(file_path, "wav")
            elif file_path.endswith('.csv'):
                data = file_io.load_csv(file_path)
                # Default sample rate if not specified
                sample_rate, ok = QInputDialog.getInt(
                    self, "Sample Rate", "Enter sample rate (Hz):",
                    10000
                )
                if not ok:
                    return
                data_array = np.asarray(data)
                if data_array.ndim == 1:
                    channel_names = ["Input 1"]
                else:
                    channel_names = [f"Input {index + 1}" for index in range(data_array.shape[1])]
                recording = Recording(data_array, sample_rate=sample_rate, metadata=RecordingMetadata(channel_names=channel_names))
            else:
                QMessageBox.warning(self, "Unsupported Format", "Unsupported file format.")
                return
            
            self.current_recording = recording
            self.display_widget.update_display(recording)
            self.save_button.setEnabled(True)
            self.recording_complete.emit(recording)
            
            QMessageBox.information(self, "Success", f"Recording loaded from:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load recording:\n{str(e)}")

    def selected_pixi_channels(self) -> list[int]:
        """Return selected Pixi input pins."""
        return [index for index, check in enumerate(self.pixi_channel_checks) if check.isChecked()]

    def selected_imu_fields(self) -> list[str]:
        """Return selected IMU fields."""
        return [field for field, check in self.imu_field_checks.items() if check.isChecked()]

    def update_imu_rate_limit(self) -> None:
        maximum = max_rate_for_fields(self.selected_imu_fields())
        self.imu_rate_spinbox.setMaximum(maximum)
        self.imu_rate_spinbox.setToolTip(
            f"Maximum {maximum} Hz for the currently selected IMU chips"
        )

    def update_pixi_input_count(self):
        """Keep Pixi amount synchronized with checked pins."""
        self.pixi_input_count_spinbox.blockSignals(True)
        self.pixi_input_count_spinbox.setValue(len(self.selected_pixi_channels()))
        self.pixi_input_count_spinbox.blockSignals(False)

    def update_pixi_channel_checks(self, count: int):
        """Select the first N Pixi pins when the amount changes."""
        for index, check in enumerate(self.pixi_channel_checks):
            check.blockSignals(True)
            check.setChecked(index < count)
            check.blockSignals(False)
