"""
Device control and status widget for the serial haptic backend.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import time

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QPushButton,
    QComboBox,
    QLabel,
    QCheckBox,
    QPlainTextEdit,
    QSpinBox,
    QDoubleSpinBox,
    QProgressBar,
)
from PyQt6.QtCore import QCoreApplication, Qt, QThread, QTimer, pyqtSignal

from hardware.haptic_device_interface import HapticDeviceInterface
from hardware.imu_config import max_rate_for_fields
from scripts.imu_flatline_sweep import format_result as format_imu_result
from scripts.imu_flatline_sweep import run_rate as run_imu_rate
from scripts.haptic_max_throughput import (
    requested_rates,
    run_duplex_trial,
    run_rx_trial,
    run_tx_trial,
    stable_rx,
    stable_tx,
)

HEALTH_THROUGHPUT_SPS = 10000
HEALTH_THROUGHPUT_DURATION_S = 30.0
HEALTH_THROUGHPUT_TOLERANCE = 0.95
HEALTH_THROUGHPUT_FRAME_SAMPLES = 128


class DeviceHealthWorker(QThread):
    """Run the short, user-facing device health checks."""

    test_started = pyqtSignal(int)
    test_finished = pyqtSignal(int, bool, str)
    completed = pyqtSignal(bool)

    def __init__(self, hardware_interface, port=None):
        super().__init__()
        self.hardware_interface = hardware_interface
        self.port = port

    def run(self):
        all_ok = True
        checks = [
            self._check_connection,
            self._check_communication,
            self._check_pixi,
            self._check_imu,
            self._check_throughput,
        ]
        for index, check in enumerate(checks):
            self.test_started.emit(index)
            try:
                ok, message = check()
            except Exception as exc:
                ok, message = False, str(exc)
            all_ok = all_ok and ok
            self.test_finished.emit(index, ok, message)
            if index == 0 and not ok:
                for skipped in range(1, len(checks)):
                    self.test_finished.emit(skipped, False, "Skipped: device is not connected")
                all_ok = False
                break
        self.completed.emit(all_ok)

    def _check_connection(self):
        if hasattr(self.hardware_interface, "is_connected") and self.hardware_interface.is_connected():
            return True, f"Connected on {getattr(self.hardware_interface, 'port', 'device')}"
        if not hasattr(self.hardware_interface, "connect"):
            return False, "The selected backend cannot connect to a device"
        port = None if self.port == "MOCK" else self.port
        if self.hardware_interface.connect(port):
            return True, f"Connected on {getattr(self.hardware_interface, 'port', 'device')}"
        errors = self.hardware_interface.recent_errors() if hasattr(self.hardware_interface, "recent_errors") else []
        return False, errors[-1] if errors else "No device responded"

    def _check_communication(self):
        if not hasattr(self.hardware_interface, "ping"):
            return True, "Connection is active"
        reply = self.hardware_interface.ping()
        ok = str(reply).startswith("OK")
        return ok, "Device responded to commands" if ok else f"Unexpected response: {reply}"

    def _status(self):
        status = self.hardware_interface.get_status()
        return asdict(status) if is_dataclass(status) else dict(status)

    def _check_pixi(self):
        status = self._status()
        ok = bool(status.get("pixi_ok", False))
        return ok, "MAX11300/Pixi is ready" if ok else "MAX11300/Pixi did not initialize"

    def _check_imu(self):
        status = self._status()
        if not bool(status.get("imu_ok", False)):
            return False, "IMU did not initialize"
        if hasattr(self.hardware_interface, "read_imu"):
            self.hardware_interface.read_imu()
        return True, "IMU is ready and responding"

    def _check_throughput(self):
        """Verify simultaneous recording/rendering at the application's 10 kS/s rate."""
        if not all(
            hasattr(self.hardware_interface, method)
            for method in (
                "diagnostic_counts",
                "configure_channels",
                "write_render_buffer",
            )
        ):
            return False, "The selected backend does not support throughput testing"

        if hasattr(self.hardware_interface, "set_render_frame_samples"):
            self.hardware_interface.set_render_frame_samples(HEALTH_THROUGHPUT_FRAME_SAMPLES)
        result = run_duplex_trial(
            self.hardware_interface,
            HEALTH_THROUGHPUT_SPS,
            HEALTH_THROUGHPUT_DURATION_S,
            HEALTH_THROUGHPUT_FRAME_SAMPLES,
        )
        minimum = HEALTH_THROUGHPUT_SPS * HEALTH_THROUGHPUT_TOLERANCE
        ok = (
            stable_tx(result)
            and result.rx_sps >= minimum
            and result.render_sps >= minimum
            and result.overruns == 0
            and (result.underruns - result.startup_underruns) == 0
        )
        measured = (
            f"RX {result.rx_ksps:.1f} / rendered {result.render_ksps:.1f} ksample/s"
        )
        if ok:
            return True, (
                f"{measured} (required ≥ {minimum / 1000:.1f}); "
                f"{result.startup_underruns} startup underruns"
            )
        details = []
        if result.crc_failures:
            details.append(f"{result.crc_failures} CRC errors")
        if result.dropped_frames:
            details.append(f"{result.dropped_frames} dropped frames")
        if result.new_errors:
            details.append(f"{result.new_errors} protocol errors")
        steady_underruns = max(0, result.underruns - result.startup_underruns)
        if result.startup_underruns:
            details.append(f"{result.startup_underruns} startup underruns")
        if steady_underruns:
            details.append(f"{steady_underruns} playback underruns")
        if result.overruns:
            details.append(f"{result.overruns} render-buffer overruns")
        suffix = f"; {', '.join(details)}" if details else ""
        return False, f"{measured}; required ≥ {minimum / 1000:.1f} each{suffix}"


class ThroughputWorker(QThread):
    """Run throughput sweeps without blocking the Qt UI thread."""

    line = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        hardware_interface,
        mode: str,
        start_rate: int,
        stop_rate: int,
        factor: float,
        duration: float,
        frame_samples: int,
        tolerance: float,
        owns_interface: bool = False,
    ):
        super().__init__()
        self.hardware_interface = hardware_interface
        self.mode = mode
        self.start_rate = start_rate
        self.stop_rate = stop_rate
        self.factor = factor
        self.duration = duration
        self.frame_samples = frame_samples
        self.tolerance = tolerance
        self.owns_interface = owns_interface

    def run(self):
        previous_timeout = getattr(self.hardware_interface, "command_timeout", None)
        previous_imu_stream = None
        previous_imu_rate = None
        try:
            self._ensure_connected()
            previous_imu_stream, previous_imu_rate = self._disable_background_streams()
            self._prepare_interface_for_sweep()
            modes = ["rx", "tx", "duplex"] if self.mode == "all" else [self.mode]
            rates = requested_rates(self.start_rate, self.stop_rate, self.factor)
            self.line.emit(
                "Connection: "
                f"port={getattr(self.hardware_interface, 'port', None)} "
                f"timeout={getattr(self.hardware_interface, 'timeout', None)} "
                f"command_timeout={getattr(self.hardware_interface, 'command_timeout', None)}"
            )
            self.line.emit(f"Rates: {rates}")
            self.line.emit(f"Frame samples: {self.frame_samples}")

            for mode in modes:
                if self.isInterruptionRequested():
                    break
                self.line.emit("")
                self.line.emit(f"[{mode.upper()}]")
                best = None

                for rate in rates:
                    if self.isInterruptionRequested():
                        break
                    result = self._run_trial(mode, rate)
                    result.ok = self._is_stable(mode, result)
                    self.line.emit(self._format_result(mode, result))
                    if not result.ok:
                        break
                    best = result
                    self.msleep(200)

                if best is None:
                    self.line.emit(f"{mode}: no stable rate found")
                elif mode == "rx":
                    self.line.emit(f"{mode}: max stable {best.rx_ksps:.2f} ksamples/s")
                elif mode == "tx":
                    self.line.emit(
                        f"{mode}: max stable rendered_e2e={best.render_ksps:.2f} "
                        f"rendered_active={best.active_render_ksps:.2f} ksamples/s"
                    )
                else:
                    self.line.emit(
                        f"{mode}: max stable rx_e2e={best.rx_ksps:.2f} "
                        f"rendered_e2e={best.render_ksps:.2f} "
                        f"rx_active={best.active_rx_ksps:.2f} "
                        f"rendered_active={best.active_render_ksps:.2f} ksamples/s"
                    )
        except Exception as exc:
            self.line.emit(f"ERROR: {exc}")
        finally:
            self._restore_background_streams(previous_imu_stream, previous_imu_rate)
            if previous_timeout is not None:
                self.hardware_interface.command_timeout = previous_timeout
            if self.owns_interface and hasattr(self.hardware_interface, "disconnect"):
                self.hardware_interface.disconnect()
            self.finished.emit()

    def _ensure_connected(self):
        if hasattr(self.hardware_interface, "is_connected") and self.hardware_interface.is_connected():
            return
        if hasattr(self.hardware_interface, "connect") and self.hardware_interface.connect():
            return
        errors = self.hardware_interface.recent_errors() if hasattr(self.hardware_interface, "recent_errors") else []
        raise RuntimeError(f"failed to connect for diagnostics: {errors}")

    def _disable_background_streams(self):
        if not hasattr(self.hardware_interface, "configure_imu_stream"):
            return None, None
        if hasattr(self.hardware_interface, "get_status"):
            try:
                self.hardware_interface.get_status()
            except Exception:
                pass
        status = getattr(self.hardware_interface, "_status", None)
        previous_enabled = bool(getattr(status, "imu_stream", False)) if status is not None else False
        previous_rate = int(getattr(status, "imu_rate", 100)) if status is not None else 100
        try:
            self.hardware_interface.configure_imu_stream(previous_rate, False)
        except Exception as exc:
            self.line.emit(f"Warning: could not disable IMU stream for diagnostics: {exc}")
        return previous_enabled, previous_rate

    def _restore_background_streams(self, previous_enabled, previous_rate):
        if previous_enabled is None or not hasattr(self.hardware_interface, "configure_imu_stream"):
            return
        try:
            self.hardware_interface.configure_imu_stream(previous_rate or 100, previous_enabled)
        except Exception as exc:
            self.line.emit(f"Warning: could not restore IMU stream: {exc}")

    def _prepare_interface_for_sweep(self):
        if hasattr(self.hardware_interface, "set_render_frame_samples"):
            self.hardware_interface.set_render_frame_samples(self.frame_samples)
        elif hasattr(self.hardware_interface, "_render_frame_samples"):
            self.hardware_interface._render_frame_samples = self.frame_samples
        if hasattr(self.hardware_interface, "set_frame_queue_size"):
            self.hardware_interface.set_frame_queue_size(512)
        if hasattr(self.hardware_interface, "command_timeout"):
            self.hardware_interface.command_timeout = max(self.hardware_interface.command_timeout, 5.0)

    def _run_trial(self, mode: str, rate: int):
        if mode == "rx":
            return run_rx_trial(self.hardware_interface, rate, self.duration)
        if mode == "tx":
            return run_tx_trial(self.hardware_interface, rate, self.duration, self.frame_samples)
        return run_duplex_trial(self.hardware_interface, rate, self.duration, self.frame_samples)

    def _is_stable(self, mode: str, result) -> bool:
        if mode == "rx":
            return stable_rx(result, self.tolerance)
        if mode == "tx":
            return (
                stable_tx(result)
                and result.active_render_sps >= result.requested_sps * self.tolerance
            )
        return (
            stable_tx(result)
            and result.active_rx_sps >= result.requested_sps * self.tolerance
            and result.active_render_sps >= result.requested_sps * self.tolerance
        )

    @staticmethod
    def _format_result(mode: str, result) -> str:
        marker = "OK" if result.ok else "FAIL"
        return (
            f"{mode:6s} request={result.requested_sps:6d} sps "
            f"rx_e2e={result.rx_ksps:7.2f} render_e2e={result.render_ksps:7.2f} ksps "
            f"rx_active={result.active_rx_ksps:7.2f} "
            f"render_active={result.active_render_ksps:7.2f} ksps "
            f"crc={result.crc_failures} drop={result.dropped_frames} "
            f"underrun={result.underruns} startup={result.startup_underruns} "
            f"overrun={result.overruns} "
            f"errors={result.new_errors} {marker} {result.note}"
        )


class ImuDiagnosticsWorker(QThread):
    """Sweep selected IMU inputs and report delivery and flatline diagnostics."""

    line = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, hardware_interface, rates, fields, duration):
        super().__init__()
        self.hardware_interface = hardware_interface
        self.rates = rates
        self.fields = fields
        self.duration = duration

    def run(self):
        try:
            self.line.emit(f"Inputs: {', '.join(self.fields)}")
            self.line.emit(f"Rates: {self.rates}")
            self.line.emit("Move the selected sensor throughout the sweep.")
            for rate in self.rates:
                if self.isInterruptionRequested():
                    break
                result = run_imu_rate(
                    self.hardware_interface,
                    rate,
                    self.duration,
                    0.5,
                    0.8,
                    self.fields,
                )
                self.line.emit(format_imu_result(result))
                self.msleep(200)
        except Exception as exc:
            self.line.emit(f"ERROR: {exc}")
        finally:
            if hasattr(self.hardware_interface, "is_running") and self.hardware_interface.is_running():
                try:
                    self.hardware_interface.stop_acquisition()
                except Exception:
                    pass
            self.finished.emit()


class DeviceStatusWidget(QWidget):
    """Compact device connection, channel configuration, and status panel."""

    def __init__(self, hardware_interface):
        super().__init__()
        self.hardware_interface = hardware_interface
        self.health_worker = None
        self.health_countdown_remaining = 0
        self.throughput_worker = None
        self.imu_diagnostics_worker = None
        self._diagnostics_reconnect_port = None
        self._diagnostics_was_connected = False
        self.setup_ui()
        self.health_countdown_timer = QTimer(self)
        self.health_countdown_timer.timeout.connect(self._update_health_countdown)
        self.refresh_ports()
        self.refresh_status()

        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(1000)

    def setup_ui(self):
        layout = QVBoxLayout()
        
        self.test_device_button = QPushButton("Test Device")
        self.test_device_button.setMinimumHeight(58)
        self.test_device_button.setFixedWidth(240)
        self.test_device_button.setStyleSheet(
            "QPushButton { font-size: 20px; font-weight: 600; padding: 12px 28px; "
            "background: #0aa9e8; color: #071521; border: none; border-radius: 7px; }"
            "QPushButton:hover { background: #35bbed; }"
            "QPushButton:disabled { background: #315569; color: #8197a5; }"
        )
        self.test_device_button.clicked.connect(self.run_device_health_check)

        results_group = QGroupBox("Device check")
        results_group_layout = QHBoxLayout()
        results_layout = QVBoxLayout()
        self.health_rows = []
        for name in (
            "Connection",
            "Communication",
            "MAX11300 / Pixi",
            "IMU sensors",
            "USB throughput",
        ):
            row = QHBoxLayout()
            name_label = QLabel(name)
            name_label.setMinimumWidth(170)
            name_label.setStyleSheet("font-weight: 600;")
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setValue(0)
            progress.setTextVisible(False)
            progress.setMaximumWidth(240)
            result = QLabel("Not tested")
            result.setWordWrap(True)
            row.addWidget(name_label)
            row.addWidget(progress)
            row.addWidget(result, 1)
            results_layout.addLayout(row)
            self.health_rows.append((progress, result))
        self.health_summary = QLabel("Press “Test Device” to begin.")
        self.health_summary.setWordWrap(True)
        self.health_summary.setStyleSheet("font-size: 15px; padding-top: 8px;")
        results_layout.addWidget(self.health_summary)
        results_group_layout.addLayout(results_layout, 1)
        results_group_layout.addSpacing(18)
        button_column = QVBoxLayout()
        button_column.addStretch()
        button_column.addWidget(self.test_device_button)
        button_column.addStretch()
        results_group_layout.addLayout(button_column)
        results_group.setLayout(results_group_layout)
        layout.addWidget(results_group)

        self.detailed_info_toggle = QCheckBox("Detailed Info")
        self.detailed_info_toggle.toggled.connect(self._toggle_detailed_info)
        layout.addWidget(self.detailed_info_toggle)

        self.detailed_panel = QWidget()
        detailed_layout = QVBoxLayout(self.detailed_panel)
        detailed_layout.setContentsMargins(0, 0, 0, 0)
        self.detailed_panel.setVisible(False)

        top_layout = QHBoxLayout()

        connection_group = QGroupBox("Connection")
        connection_layout = QHBoxLayout()
        self.port_combo = QComboBox()
        connection_layout.addWidget(QLabel("Port:"))
        connection_layout.addWidget(self.port_combo)

        self.refresh_ports_button = QPushButton("Refresh")
        self.refresh_ports_button.clicked.connect(self.refresh_ports)
        connection_layout.addWidget(self.refresh_ports_button)

        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.toggle_connection)
        connection_layout.addWidget(self.connect_button)
        connection_layout.addStretch()
        connection_group.setLayout(connection_layout)
        top_layout.addWidget(connection_group, 1)

        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()
        self.status_text = QPlainTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(100)
        self.status_text.setMinimumWidth(420)
        status_layout.addWidget(self.status_text)
        status_group.setLayout(status_layout)
        top_layout.addWidget(status_group, 2)
        detailed_layout.addLayout(top_layout)

        imu_group = QGroupBox("IMU")
        imu_layout = QVBoxLayout()
        imu_button_layout = QHBoxLayout()
        self.imu_status_button = QPushButton("Check IMU")
        self.imu_status_button.clicked.connect(self.check_imu_status)
        imu_button_layout.addWidget(self.imu_status_button)
        self.imu_read_button = QPushButton("Read IMU")
        self.imu_read_button.clicked.connect(self.read_imu)
        imu_button_layout.addWidget(self.imu_read_button)
        self.imu_stream_check = QCheckBox("Stream")
        imu_button_layout.addWidget(self.imu_stream_check)
        imu_button_layout.addWidget(QLabel("Rate:"))
        self.imu_stream_rate_spinbox = QSpinBox()
        # This diagnostic displays every sensor, so it uses the four-chip limit.
        self.imu_stream_rate_spinbox.setRange(1, 800)
        self.imu_stream_rate_spinbox.setSingleStep(1000)
        self.imu_stream_rate_spinbox.setValue(100)
        imu_button_layout.addWidget(self.imu_stream_rate_spinbox)
        self.imu_apply_stream_button = QPushButton("Apply")
        self.imu_apply_stream_button.clicked.connect(self.apply_imu_stream)
        imu_button_layout.addWidget(self.imu_apply_stream_button)
        self.imu_read_stream_button = QPushButton("Read Stream")
        self.imu_read_stream_button.clicked.connect(self.read_imu_stream)
        imu_button_layout.addWidget(self.imu_read_stream_button)
        imu_button_layout.addStretch()
        imu_layout.addLayout(imu_button_layout)
        self.imu_text = QPlainTextEdit()
        self.imu_text.setReadOnly(True)
        self.imu_text.setMaximumHeight(120)
        imu_layout.addWidget(self.imu_text)
        imu_group.setLayout(imu_layout)
        detailed_layout.addWidget(imu_group)

        imu_diagnostics_group = QGroupBox("IMU Stream Diagnostics")
        imu_diagnostics_layout = QVBoxLayout()
        imu_diagnostics_controls = QHBoxLayout()
        imu_diagnostics_controls.addWidget(QLabel("Inputs:"))
        self.imu_diag_inputs_combo = QComboBox()
        self.imu_diag_inputs_combo.addItems(
            ["Accelerometer", "Gyroscope", "Magnetometer", "Pressure / temperature", "All sensors"]
        )
        imu_diagnostics_controls.addWidget(self.imu_diag_inputs_combo)
        imu_diagnostics_controls.addWidget(QLabel("Seconds per rate:"))
        self.imu_diag_duration_spinbox = QDoubleSpinBox()
        self.imu_diag_duration_spinbox.setRange(1.0, 30.0)
        self.imu_diag_duration_spinbox.setValue(5.0)
        imu_diagnostics_controls.addWidget(self.imu_diag_duration_spinbox)
        self.run_imu_diag_button = QPushButton("Run IMU Sweep")
        self.run_imu_diag_button.clicked.connect(self.run_imu_diagnostics)
        imu_diagnostics_controls.addWidget(self.run_imu_diag_button)
        self.stop_imu_diag_button = QPushButton("Stop")
        self.stop_imu_diag_button.setEnabled(False)
        self.stop_imu_diag_button.clicked.connect(self.stop_imu_diagnostics)
        imu_diagnostics_controls.addWidget(self.stop_imu_diag_button)
        imu_diagnostics_controls.addStretch()
        imu_diagnostics_layout.addLayout(imu_diagnostics_controls)
        self.imu_diagnostics_text = QPlainTextEdit()
        self.imu_diagnostics_text.setReadOnly(True)
        self.imu_diagnostics_text.setMinimumHeight(150)
        imu_diagnostics_layout.addWidget(self.imu_diagnostics_text)
        imu_diagnostics_group.setLayout(imu_diagnostics_layout)
        detailed_layout.addWidget(imu_diagnostics_group)

        error_group = QGroupBox("Recent Protocol Errors")
        error_layout = QVBoxLayout()
        self.error_text = QPlainTextEdit()
        self.error_text.setReadOnly(True)
        self.error_text.setMaximumHeight(90)
        error_layout.addWidget(self.error_text)
        error_group.setLayout(error_layout)
        detailed_layout.addWidget(error_group)

        diagnostics_group = QGroupBox("Throughput Diagnostics")
        diagnostics_layout = QVBoxLayout()

        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("Mode:"))
        self.diag_mode_combo = QComboBox()
        self.diag_mode_combo.addItems(["rx", "tx", "duplex", "all"])
        settings_layout.addWidget(self.diag_mode_combo)

        settings_layout.addWidget(QLabel("Start:"))
        self.diag_start_spinbox = QSpinBox()
        self.diag_start_spinbox.setRange(10, 200000)
        self.diag_start_spinbox.setValue(500)
        settings_layout.addWidget(self.diag_start_spinbox)

        settings_layout.addWidget(QLabel("Stop:"))
        self.diag_stop_spinbox = QSpinBox()
        self.diag_stop_spinbox.setRange(10, 200000)
        self.diag_stop_spinbox.setValue(20000)
        settings_layout.addWidget(self.diag_stop_spinbox)

        settings_layout.addWidget(QLabel("Factor:"))
        self.diag_factor_spinbox = QDoubleSpinBox()
        self.diag_factor_spinbox.setRange(1.1, 10.0)
        self.diag_factor_spinbox.setDecimals(2)
        self.diag_factor_spinbox.setValue(1.5)
        settings_layout.addWidget(self.diag_factor_spinbox)

        diagnostics_layout.addLayout(settings_layout)

        timing_layout = QHBoxLayout()
        timing_layout.addWidget(QLabel("Duration (s):"))
        self.diag_duration_spinbox = QDoubleSpinBox()
        self.diag_duration_spinbox.setRange(0.2, 30.0)
        self.diag_duration_spinbox.setDecimals(1)
        self.diag_duration_spinbox.setValue(10.0)
        timing_layout.addWidget(self.diag_duration_spinbox)

        timing_layout.addWidget(QLabel("Frame samples:"))
        self.diag_frame_spinbox = QSpinBox()
        self.diag_frame_spinbox.setRange(1, 128)
        self.diag_frame_spinbox.setValue(128)
        timing_layout.addWidget(self.diag_frame_spinbox)

        timing_layout.addWidget(QLabel("Tolerance:"))
        self.diag_tolerance_spinbox = QDoubleSpinBox()
        self.diag_tolerance_spinbox.setRange(0.1, 1.0)
        self.diag_tolerance_spinbox.setDecimals(2)
        self.diag_tolerance_spinbox.setSingleStep(0.05)
        self.diag_tolerance_spinbox.setValue(0.85)
        timing_layout.addWidget(self.diag_tolerance_spinbox)

        self.run_diag_button = QPushButton("Run")
        self.run_diag_button.clicked.connect(self.run_throughput_diagnostics)
        timing_layout.addWidget(self.run_diag_button)

        self.stop_diag_button = QPushButton("Stop")
        self.stop_diag_button.setEnabled(False)
        self.stop_diag_button.clicked.connect(self.stop_throughput_diagnostics)
        timing_layout.addWidget(self.stop_diag_button)
        timing_layout.addStretch()
        diagnostics_layout.addLayout(timing_layout)

        self.diagnostics_text = QPlainTextEdit()
        self.diagnostics_text.setReadOnly(True)
        diagnostics_layout.addWidget(self.diagnostics_text)

        diagnostics_group.setLayout(diagnostics_layout)
        detailed_layout.addWidget(diagnostics_group, 1)
        layout.addWidget(self.detailed_panel, 1)
        layout.addStretch()

        self.setLayout(layout)

    def _toggle_detailed_info(self, visible: bool):
        self.detailed_panel.setVisible(visible)

    def run_device_health_check(self):
        if self.health_worker and self.health_worker.isRunning():
            return
        self.timer.stop()
        self.test_device_button.setEnabled(False)
        self.health_summary.setText("Testing device…")
        self.health_summary.setStyleSheet("font-size: 15px; padding-top: 8px; color: #0aa9e8;")
        for progress, result in self.health_rows:
            progress.setRange(0, 100)
            progress.setValue(0)
            progress.setStyleSheet("")
            result.setText("Waiting…")
            result.setStyleSheet("color: #9da8b8;")

        self.health_worker = DeviceHealthWorker(
            self.hardware_interface,
            self.port_combo.currentText(),
        )
        self.health_worker.test_started.connect(self._health_test_started)
        self.health_worker.test_finished.connect(self._health_test_finished)
        self.health_worker.completed.connect(self._health_check_completed)
        self.health_worker.start()

    def _health_test_started(self, index: int):
        progress, result = self.health_rows[index]
        progress.setRange(0, 0)
        if index == len(self.health_rows) - 1:
            self.health_countdown_remaining = int(HEALTH_THROUGHPUT_DURATION_S)
            self.health_countdown_timer.start(1000)
            self._show_health_countdown()
        else:
            result.setText("Testing…")
        result.setStyleSheet("color: #0aa9e8;")

    def _health_test_finished(self, index: int, ok: bool, message: str):
        if index == len(self.health_rows) - 1:
            self.health_countdown_timer.stop()
            self.health_countdown_remaining = 0
        progress, result = self.health_rows[index]
        progress.setRange(0, 100)
        progress.setValue(100)
        if ok:
            progress.setStyleSheet(
                "QProgressBar::chunk { background: #51cf8a; border-radius: 3px; }"
            )
            result.setText(f"✓ {message}")
            result.setStyleSheet("color: #51cf8a; font-weight: 600;")
        else:
            progress.setStyleSheet(
                "QProgressBar::chunk { background: #ef6673; border-radius: 3px; }"
            )
            result.setText(f"✕ {message}")
            result.setStyleSheet("color: #ef6673; font-weight: 600;")

    def _update_health_countdown(self):
        self.health_countdown_remaining = max(0, self.health_countdown_remaining - 1)
        if self.health_countdown_remaining == 0:
            self.health_countdown_timer.stop()
            _, result = self.health_rows[-1]
            result.setText("Finishing throughput test…")
            self.health_summary.setText("Finishing USB throughput test…")
        else:
            self._show_health_countdown()

    def _show_health_countdown(self):
        if not self.health_rows:
            return
        _, result = self.health_rows[-1]
        seconds = self.health_countdown_remaining
        result.setText(f"Testing… {seconds} seconds remaining")
        self.health_summary.setText(f"Testing USB throughput… {seconds} seconds remaining")

    def _health_check_completed(self, all_ok: bool):
        self.health_countdown_timer.stop()
        self.test_device_button.setEnabled(True)
        if all_ok:
            self.health_summary.setText("✓ Device is working as expected.")
            self.health_summary.setStyleSheet(
                "font-size: 16px; font-weight: 600; padding-top: 8px; color: #51cf8a;"
            )
        else:
            self.health_summary.setText(
                "One or more checks failed. Open Detailed Info for troubleshooting."
            )
            self.health_summary.setStyleSheet(
                "font-size: 15px; font-weight: 600; padding-top: 8px; color: #ef6673;"
            )
        self.health_worker = None
        self.refresh_status()
        self.timer.start(1000)

    def refresh_ports(self):
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = []
        if hasattr(self.hardware_interface, "get_available_ports"):
            ports = self.hardware_interface.get_available_ports()
        if not ports:
            ports = ["MOCK"]
        self.port_combo.addItems(ports)
        if current:
            index = self.port_combo.findText(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

    def toggle_connection(self):
        if self._is_connected():
            if hasattr(self.hardware_interface, "disconnect"):
                self.hardware_interface.disconnect()
        else:
            port = self.port_combo.currentText()
            if port == "MOCK":
                port = None
            if hasattr(self.hardware_interface, "connect"):
                self.hardware_interface.connect(port)
        self.refresh_status()

    def refresh_status(self):
        if self.throughput_worker and self.throughput_worker.isRunning():
            return
        if hasattr(self.hardware_interface, "is_running") and self.hardware_interface.is_running():
            return
        if hasattr(self.hardware_interface, "is_rendering") and self.hardware_interface.is_rendering():
            return
        status = {}
        if hasattr(self.hardware_interface, "get_status"):
            status_obj = self.hardware_interface.get_status()
            status = asdict(status_obj) if is_dataclass(status_obj) else dict(status_obj)
        connected = self._is_connected(status)
        self.connect_button.setText("Disconnect" if connected else "Connect")

        lines = [
            f"Connected: {connected}",
            f"Port: {status.get('port')}",
            f"Firmware: {status.get('firmware', 'unknown')}",
            f"Pixi OK: {status.get('pixi_ok', False)}",
            f"IMU OK: {status.get('imu_ok', False)}",
            f"IMU stream: {status.get('imu_stream', False)} @ {status.get('imu_rate', 0)} Hz",
            f"Acquisition: {status.get('acquiring', False)}",
            f"Rendering: {status.get('rendering', False)}",
            f"Dropped frames: {status.get('dropped_frames', 0)}",
            f"Underruns: {status.get('underruns', 0)}",
            f"Startup underruns: {status.get('render_startup_underruns', 0)}",
            f"Render buffer overruns: {status.get('render_overruns', 0)}",
            f"Render overvolts: {status.get('render_overvolts', 0)}",
            f"Render samples: {status.get('render_samples', 0)}",
            f"Render bias samples: {status.get('render_bias_samples', 0)}",
            f"Underrun bias samples: {status.get('render_underrun_bias_samples', 0)}",
            f"Late render ticks: {status.get('render_late_ticks', 0)}",
            f"Render due max: {status.get('render_due_max', 0)}",
            f"Render SPI failures: {status.get('render_spi_failures', 0)}",
            f"Render tick max: {status.get('render_tick_max_us', 0)} us",
            f"USB RX queued/max: {status.get('rx_queue_bytes', 0)} / {status.get('rx_queue_max', 0)} bytes",
            f"CRC failures: {status.get('rx_crc_failures', 0)}",
            f"IMU queued: {status.get('imu_fill', 0)}",
        ]
        self.status_text.setPlainText("\n".join(lines))

        errors = []
        if hasattr(self.hardware_interface, "recent_errors"):
            errors = self.hardware_interface.recent_errors()
        self.error_text.setPlainText("\n".join(errors[-8:]))

    def _is_connected(self, status=None) -> bool:
        if hasattr(self.hardware_interface, "is_connected"):
            return bool(self.hardware_interface.is_connected())
        if status:
            return bool(status.get("connected", False))
        return False

    def run_throughput_diagnostics(self):
        if not self._is_connected():
            self.diagnostics_text.setPlainText("Connect to the serial device first.")
            return

        port = getattr(self.hardware_interface, "port", None) or self.port_combo.currentText()
        if port == "MOCK":
            self.diagnostics_text.setPlainText("Select a serial device before running diagnostics.")
            return

        self.diagnostics_text.clear()
        self.timer.stop()
        self.run_diag_button.setEnabled(False)
        self.stop_diag_button.setEnabled(True)

        self._diagnostics_reconnect_port = port
        self._diagnostics_was_connected = self._is_connected()
        baudrate = getattr(self.hardware_interface, "baudrate", 921600)
        if hasattr(self.hardware_interface, "disconnect"):
            self.hardware_interface.disconnect()

        diagnostic_interface = HapticDeviceInterface(
            port=port,
            baudrate=baudrate,
            timeout=0.2,
            command_timeout=5.0,
            frame_queue_size=512,
            render_frame_samples=self.diag_frame_spinbox.value(),
        )

        self.throughput_worker = ThroughputWorker(
            diagnostic_interface,
            self.diag_mode_combo.currentText(),
            self.diag_start_spinbox.value(),
            self.diag_stop_spinbox.value(),
            self.diag_factor_spinbox.value(),
            self.diag_duration_spinbox.value(),
            self.diag_frame_spinbox.value(),
            self.diag_tolerance_spinbox.value(),
            owns_interface=True,
        )
        self.throughput_worker.line.connect(self.append_diagnostic_line)
        self.throughput_worker.finished.connect(self.on_throughput_finished)
        self.throughput_worker.start()

    def _selected_imu_diagnostic_fields(self):
        return {
            "Accelerometer": ["accel_x", "accel_y", "accel_z"],
            "Gyroscope": ["gyro_x", "gyro_y", "gyro_z"],
            "Magnetometer": ["mag_x", "mag_y", "mag_z"],
            "Pressure / temperature": ["pressure", "temperature"],
            "All sensors": [
                "accel_x", "accel_y", "accel_z",
                "gyro_x", "gyro_y", "gyro_z",
                "mag_x", "mag_y", "mag_z",
                "pressure", "temperature",
            ],
        }[self.imu_diag_inputs_combo.currentText()]

    def run_imu_diagnostics(self):
        if not self._is_connected():
            self.imu_diagnostics_text.setPlainText("Connect to the serial device first.")
            return
        if self.throughput_worker and self.throughput_worker.isRunning():
            self.imu_diagnostics_text.setPlainText("Stop throughput diagnostics first.")
            return

        fields = self._selected_imu_diagnostic_fields()
        maximum = max_rate_for_fields(fields)
        rates = [
            rate for rate in (25, 50, 100, 200, 400, 800, 1000, 1600, 3200)
            if rate <= maximum
        ]
        self.imu_diagnostics_text.clear()
        self.timer.stop()
        self.run_imu_diag_button.setEnabled(False)
        self.run_diag_button.setEnabled(False)
        self.stop_imu_diag_button.setEnabled(True)
        self.imu_diagnostics_worker = ImuDiagnosticsWorker(
            self.hardware_interface,
            rates,
            fields,
            self.imu_diag_duration_spinbox.value(),
        )
        self.imu_diagnostics_worker.line.connect(
            self.imu_diagnostics_text.appendPlainText
        )
        self.imu_diagnostics_worker.finished.connect(
            self.on_imu_diagnostics_finished
        )
        self.imu_diagnostics_worker.start()

    def stop_imu_diagnostics(self):
        if self.imu_diagnostics_worker and self.imu_diagnostics_worker.isRunning():
            self.imu_diagnostics_worker.requestInterruption()
            self.imu_diagnostics_text.appendPlainText(
                "Stopping after the current rate..."
            )

    def on_imu_diagnostics_finished(self):
        self.run_imu_diag_button.setEnabled(True)
        self.run_diag_button.setEnabled(True)
        self.stop_imu_diag_button.setEnabled(False)
        self.imu_diagnostics_worker = None
        self.timer.start(1000)
        self.refresh_status()

    def stop_throughput_diagnostics(self):
        if self.throughput_worker and self.throughput_worker.isRunning():
            self.throughput_worker.requestInterruption()
            self.append_diagnostic_line("Stopping after current trial...")

    def append_diagnostic_line(self, line: str):
        self.diagnostics_text.appendPlainText(line)

    def on_throughput_finished(self):
        if self._diagnostics_was_connected and self._diagnostics_reconnect_port and hasattr(self.hardware_interface, "connect"):
            self.hardware_interface.connect(self._diagnostics_reconnect_port)
        self._diagnostics_reconnect_port = None
        self._diagnostics_was_connected = False
        self.run_diag_button.setEnabled(True)
        self.stop_diag_button.setEnabled(False)
        self.timer.start(1000)
        self.refresh_status()

    def check_imu_status(self):
        if not self._is_connected():
            self.imu_text.setPlainText("Connect to the serial device first.")
            return
        if not hasattr(self.hardware_interface, "read_imu_status"):
            self.imu_text.setPlainText("Current hardware backend does not expose IMU commands.")
            return
        try:
            status = self.hardware_interface.read_imu_status()
            lines = [
                f"Accelerometer: {status.get('accel_ok', False)}",
                f"Gyro: {status.get('gyro_ok', False)}",
                f"Magnetometer: {status.get('mag_ok', False)}",
                f"BMP280: {status.get('bmp_ok', False)}",
                f"BMP280 address: 0x{int(status.get('bmp_addr', 0)):02X}",
            ]
            self.imu_text.setPlainText("\n".join(lines))
        except Exception as exc:
            self.imu_text.setPlainText(f"IMU status failed: {exc}")

    def read_imu(self):
        if not self._is_connected():
            self.imu_text.setPlainText("Connect to the serial device first.")
            return
        if not hasattr(self.hardware_interface, "read_imu"):
            self.imu_text.setPlainText("Current hardware backend does not expose IMU commands.")
            return
        try:
            sample = self.hardware_interface.read_imu()
            accel = sample.get("accel", [0, 0, 0])
            gravity = sum(float(value) ** 2 for value in accel) ** 0.5
            lines = [
                f"OK: {sample.get('ok', False)}",
                f"Accel: {[round(float(value), 4) for value in accel]} g",
                f"Accel magnitude: {gravity:.4f} g (about 1 g while stationary)",
                f"Accel raw: {sample.get('accel_raw', [0, 0, 0])} counts",
                f"Gyro raw: {sample.get('gyro', [0, 0, 0])}",
                f"Mag raw: {sample.get('mag', [0, 0, 0])}",
                f"BMP pressure raw: {sample.get('bmp_pressure_raw', 0)}",
                f"BMP temperature raw: {sample.get('bmp_temperature_raw', 0)}",
            ]
            self.imu_text.setPlainText("\n".join(lines))
        except Exception as exc:
            self.imu_text.setPlainText(f"IMU read failed: {exc}")

    def apply_imu_stream(self):
        if not self._is_connected():
            self.imu_text.setPlainText("Connect to the serial device first.")
            return
        if not hasattr(self.hardware_interface, "configure_imu_stream"):
            self.imu_text.setPlainText("Current hardware backend does not expose IMU stream commands.")
            return
        try:
            rate = self.imu_stream_rate_spinbox.value()
            enabled = self.imu_stream_check.isChecked()
            reply = self.hardware_interface.configure_imu_stream(
                rate, enabled, [
                    "accel_x", "gyro_x", "mag_x", "pressure", "temperature"
                ]
            )
            self.imu_text.setPlainText(f"{reply}\nIMU stream {'enabled' if enabled else 'disabled'} at {rate} Hz.")
            self.refresh_status()
        except Exception as exc:
            self.imu_text.setPlainText(f"IMU stream config failed: {exc}")

    def read_imu_stream(self):
        if not self._is_connected():
            self.imu_text.setPlainText("Connect to the serial device first.")
            return
        if not hasattr(self.hardware_interface, "read_available_imu"):
            self.imu_text.setPlainText("Current hardware backend does not expose queued IMU samples.")
            return
        if not hasattr(self.hardware_interface, "configure_imu_stream"):
            self.imu_text.setPlainText("Current hardware backend does not expose IMU stream commands.")
            return

        started_acquisition = False
        stream_was_enabled = self.imu_stream_check.isChecked()
        rate = self.imu_stream_rate_spinbox.value()
        samples = []
        try:
            self.hardware_interface.configure_imu_stream(
                rate, True, [
                    "accel_x", "gyro_x", "mag_x", "pressure", "temperature"
                ]
            )
            if hasattr(self.hardware_interface, "is_running") and not self.hardware_interface.is_running():
                self.hardware_interface.start_acquisition()
                started_acquisition = True

            self.imu_text.setPlainText("Waiting for IMU stream samples...")
            QCoreApplication.processEvents()

            deadline = time.monotonic() + max(0.25, min(1.0, 3.0 / max(1, rate)))
            while time.monotonic() < deadline and len(samples) < 8:
                samples.extend(self.hardware_interface.read_available_imu(8 - len(samples)))
                if len(samples) >= 8:
                    break
                time.sleep(0.02)
        except Exception as exc:
            self.imu_text.setPlainText(f"IMU stream read failed: {exc}")
            return
        finally:
            if started_acquisition and hasattr(self.hardware_interface, "stop_acquisition"):
                try:
                    self.hardware_interface.stop_acquisition()
                except Exception:
                    pass
            if not stream_was_enabled and hasattr(self.hardware_interface, "configure_imu_stream"):
                try:
                    self.hardware_interface.configure_imu_stream(rate, False)
                except Exception:
                    pass
            self.imu_stream_check.setChecked(stream_was_enabled)
            self.refresh_status()

        if not samples:
            self.imu_text.setPlainText("No IMU stream samples received. Check that IMU is OK and firmware emits IMU frames during acquisition.")
            return
        self._show_imu_stream_samples(samples)

    def _show_imu_stream_samples(self, samples):
        latest = samples[-1]
        accel = latest.get("accel", [0, 0, 0])
        gravity = sum(float(value) ** 2 for value in accel) ** 0.5
        lines = [
            f"Stream samples read: {len(samples)}",
            f"Timestamp us: {latest.get('timestamp_us', 0)}",
            f"OK: {latest.get('ok', False)}",
            f"Accel: {[round(float(value), 4) for value in accel]} g",
            f"Accel magnitude: {gravity:.4f} g (about 1 g while stationary)",
            f"Accel raw: {latest.get('accel_raw', [0, 0, 0])} counts",
            f"Gyro raw: {latest.get('gyro', [0, 0, 0])}",
            f"Mag raw: {latest.get('mag', [0, 0, 0])}",
            f"BMP pressure raw: {latest.get('bmp_pressure_raw', 0)}",
            f"BMP temperature raw: {latest.get('bmp_temperature_raw', 0)}",
        ]
        self.imu_text.setPlainText("\n".join(lines))
