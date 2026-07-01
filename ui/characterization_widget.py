"""
Characterization Widget
UI for actuator characterization module.
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
    QLabel, QProgressBar, QCheckBox, QGridLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
import pyqtgraph as pg
import numpy as np
from processing.characterization import Characterizer, ActuatorCharacterization


class CharacterizationWorker(QThread):
    """Worker thread for characterization."""
    
    progress = pyqtSignal(int)
    finished = pyqtSignal(ActuatorCharacterization)
    error = pyqtSignal(str)
    
    def __init__(self, characterizer, excitation, response, actuator_name, excitation_type):
        super().__init__()
        self.characterizer = characterizer
        self.excitation = excitation
        self.response = response
        self.actuator_name = actuator_name
        self.excitation_type = excitation_type
    
    def run(self):
        """Run characterization in thread."""
        try:
            result = self.characterizer.characterize(
                self.excitation,
                self.response,
                self.actuator_name,
                self.excitation_type
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class CharacterizationWidget(QWidget):
    """Widget for actuator characterization module."""
    
    characterization_complete = pyqtSignal(ActuatorCharacterization)
    
    def __init__(self, recording_interface, sample_rate: int = 44100):
        super().__init__()
        self.recording_interface = recording_interface
        self.characterizer = Characterizer(sample_rate)
        self.sample_rate = sample_rate
        self.current_characterization = None
        self.characterization_worker = None
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI elements."""
        layout = QVBoxLayout()
        
        channel_group = QGroupBox("Channel Selection")
        channel_layout = QVBoxLayout()

        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Pixi output:"))
        self.output_channel_spinbox = QSpinBox()
        self.output_channel_spinbox.setRange(0, 19)
        self.output_channel_spinbox.setValue(1)
        output_layout.addWidget(self.output_channel_spinbox)
        output_layout.addStretch()
        channel_layout.addLayout(output_layout)

        input_layout = QHBoxLayout()
        pixi_group = QGroupBox("Pixi Response Inputs")
        pixi_layout = QGridLayout()
        self.pixi_response_checks = []
        for channel in range(20):
            check = QCheckBox(str(channel))
            check.setChecked(channel == 0)
            self.pixi_response_checks.append(check)
            pixi_layout.addWidget(check, channel // 10, channel % 10)
        pixi_group.setLayout(pixi_layout)
        input_layout.addWidget(pixi_group)

        imu_group = QGroupBox("IMU Response Fields")
        imu_layout = QVBoxLayout()
        imu_rate_layout = QHBoxLayout()
        imu_rate_layout.addWidget(QLabel("Rate (Hz):"))
        self.imu_rate_spinbox = QSpinBox()
        self.imu_rate_spinbox.setRange(1, 1000)
        self.imu_rate_spinbox.setValue(100)
        imu_rate_layout.addWidget(self.imu_rate_spinbox)
        imu_rate_layout.addStretch()
        imu_layout.addLayout(imu_rate_layout)
        imu_grid = QGridLayout()
        self.imu_field_checks = {}
        for index, (field, label) in enumerate(self._imu_field_labels()):
            check = QCheckBox(label)
            self.imu_field_checks[field] = check
            imu_grid.addWidget(check, index // 3, index % 3)
        imu_layout.addLayout(imu_grid)
        imu_group.setLayout(imu_layout)
        input_layout.addWidget(imu_group)
        channel_layout.addLayout(input_layout)

        channel_group.setLayout(channel_layout)
        layout.addWidget(channel_group)
        
        # Excitation signal
        excitation_group = QGroupBox("Excitation Signal")
        excitation_layout = QVBoxLayout()
        
        # Type selection
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Excitation Type:"))
        self.excitation_combo = QComboBox()
        self.excitation_combo.addItems(["Sweep", "White Noise", "Impulse"])
        self.excitation_combo.currentTextChanged.connect(self.on_excitation_changed)
        type_layout.addWidget(self.excitation_combo)
        type_layout.addStretch()
        excitation_layout.addLayout(type_layout)
        
        # Frequency range (for sweep)
        freq_layout = QHBoxLayout()
        freq_layout.addWidget(QLabel("Freq Range (Hz):"))
        
        self.freq_start_spinbox = QSpinBox()
        self.freq_start_spinbox.setMinimum(1)
        self.freq_start_spinbox.setMaximum(10000)
        self.freq_start_spinbox.setValue(10)
        freq_layout.addWidget(self.freq_start_spinbox)
        
        freq_layout.addWidget(QLabel("to"))
        
        self.freq_end_spinbox = QSpinBox()
        self.freq_end_spinbox.setMinimum(1)
        self.freq_end_spinbox.setMaximum(20000)
        self.freq_end_spinbox.setValue(300)
        freq_layout.addWidget(self.freq_end_spinbox)
        
        freq_layout.addStretch()
        excitation_layout.addLayout(freq_layout)
        
        # Duration
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("Duration (s):"))
        self.duration_spinbox = QDoubleSpinBox()
        self.duration_spinbox.setMinimum(0.1)
        self.duration_spinbox.setMaximum(60.0)
        self.duration_spinbox.setValue(2.0)
        duration_layout.addWidget(self.duration_spinbox)
        duration_layout.addStretch()
        excitation_layout.addLayout(duration_layout)
        
        excitation_group.setLayout(excitation_layout)
        layout.addWidget(excitation_group)
        
        # Control buttons
        control_layout = QHBoxLayout()
        
        self.generate_button = QPushButton("Generate & Run Characterization")
        self.generate_button.clicked.connect(self.run_characterization)
        control_layout.addWidget(self.generate_button)
        
        self.save_button = QPushButton("Save Characterization")
        self.save_button.setEnabled(False)
        control_layout.addWidget(self.save_button)
        
        control_layout.addStretch()
        layout.addLayout(control_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Transfer function plot
        results_group = QGroupBox("Transfer Function")
        results_layout = QVBoxLayout()
        
        # Info label
        self.tf_info_label = QLabel("No characterization data")
        self.tf_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        results_layout.addWidget(self.tf_info_label)
        
        # Setup pyqtgraph plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#ffffff")
        self.plot_widget.setLabel('left', 'Magnitude', units='dB')
        self.plot_widget.setLabel('bottom', 'Frequency', units='Hz')
        self.plot_widget.setTitle('Transfer Function')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setMinimumHeight(160)
        self.plot_widget.setLogMode(x=True, y=False)
        
        # Configure plot appearance
        self.plot_widget.getPlotItem().getAxis('left').setPen(pg.mkPen(color="#617086", width=1))
        self.plot_widget.getPlotItem().getAxis('bottom').setPen(pg.mkPen(color="#617086", width=1))
        self.plot_widget.getPlotItem().getAxis('left').setTextPen("#263246")
        self.plot_widget.getPlotItem().getAxis('bottom').setTextPen("#263246")
        
        results_layout.addWidget(self.plot_widget)
        
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)
        
        layout.addStretch()
        self.setLayout(layout)
    
    def on_excitation_changed(self):
        """Handle excitation type change."""
        excitation_type = self.excitation_combo.currentText()
        
        # Show/hide relevant parameters
        self.freq_start_spinbox.setVisible(excitation_type == "Sweep")
        self.freq_end_spinbox.setVisible(excitation_type == "Sweep")
    
    def run_characterization(self):
        """Run actuator characterization."""
        try:
            # Generate excitation signal
            duration = self.duration_spinbox.value()
            excitation_type = self.excitation_combo.currentText().lower()
            
            if excitation_type == "sweep":
                excitation = self.characterizer.generate_sweep(
                    self.freq_start_spinbox.value(),
                    self.freq_end_spinbox.value(),
                    duration,
                    self.sample_rate
                )
            elif excitation_type == "white noise":
                excitation = self.characterizer.generate_white_noise(duration, self.sample_rate)
            else:  # impulse
                excitation = self.characterizer.generate_impulse(duration, self.sample_rate)
            
            # TODO: link with recording interface to get actual response from device
            # Simulate response (in real use, would record from device)
            pixi_inputs = self.selected_pixi_inputs()
            imu_fields = self.selected_imu_fields()
            output_channels = [self.output_channel_spinbox.value()]
            response = self.recording_interface.record_response(
                excitation,
                input_channels=pixi_inputs,
                output_channels=output_channels,
                imu_fields=imu_fields,
                imu_sample_rate=self.imu_rate_spinbox.value(),
            )

            # Run characterization in thread
            self.characterization_worker = CharacterizationWorker(
                self.characterizer,
                excitation,
                response,
                self.measurement_name(output_channels, pixi_inputs, imu_fields),
                excitation_type
            )
            self.characterization_worker.finished.connect(self.on_characterization_complete)
            self.characterization_worker.error.connect(self.on_characterization_error)
            self.characterization_worker.start()
            
            self.generate_button.setEnabled(False)
            self.progress_bar.setVisible(True)
        except Exception as e:
            print(f"Error: {e}")

    
    def on_characterization_complete(self, characterization: ActuatorCharacterization):
        """Handle characterization completion."""
        self.current_characterization = characterization
        self.save_button.setEnabled(True)
        self.generate_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        # Update results table
        self.update_results()
        
        self.characterization_complete.emit(characterization)
    
    def on_characterization_error(self, error: str):
        """Handle characterization error."""
        print(f"Characterization error: {error}")
        self.generate_button.setEnabled(True)
        self.progress_bar.setVisible(False)
    
    def update_results(self):
        """Update results display."""
        if not self.current_characterization:
            return
        
        # Clear previous plot
        self.plot_widget.clear()
        
        # Plot transfer function
        if hasattr(self.current_characterization, 'magnitude') and hasattr(self.current_characterization, 'phase'):
            freqs = self.current_characterization.frequencies
            magnitude_db = self.current_characterization.magnitude

            pen = pg.mkPen(color='b', width=2)
            self.plot_widget.plot(freqs, magnitude_db, pen=pen, name='Transfer Function')

    def selected_pixi_inputs(self) -> list[int]:
        return [index for index, check in enumerate(self.pixi_response_checks) if check.isChecked()]

    def selected_imu_fields(self) -> list[str]:
        return [field for field, check in self.imu_field_checks.items() if check.isChecked()]

    @staticmethod
    def _imu_field_labels() -> list[tuple[str, str]]:
        return [
            ("accel_x", "Accel X"),
            ("accel_y", "Accel Y"),
            ("accel_z", "Accel Z"),
            ("gyro_x", "Gyro X"),
            ("gyro_y", "Gyro Y"),
            ("gyro_z", "Gyro Z"),
            ("mag_x", "Mag X"),
            ("mag_y", "Mag Y"),
            ("mag_z", "Mag Z"),
            ("pressure", "Pressure"),
            ("temperature", "Temperature"),
        ]

    @staticmethod
    def measurement_name(output_channels: list[int], pixi_inputs: list[int], imu_fields: list[str]) -> str:
        sources = []
        if pixi_inputs:
            sources.append("Pixi " + ",".join(str(channel) for channel in pixi_inputs))
        if imu_fields:
            sources.append("IMU " + ",".join(imu_fields))
        response = " + ".join(sources) if sources else "No response"
        return f"Pixi out {','.join(str(channel) for channel in output_channels)} -> {response}"
        
