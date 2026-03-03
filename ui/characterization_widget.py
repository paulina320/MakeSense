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
    QLabel, QProgressBar, QTableWidget, QTableWidgetItem,
    QPlainTextEdit
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
        
        # Device selection
        device_group = QGroupBox("Device Selection")
        device_layout = QVBoxLayout()
        
        device_select_layout = QHBoxLayout()
        device_select_layout.addWidget(QLabel("Actuator:"))
        self.actuator_combo = QComboBox()
        self.actuator_combo.addItems(["Haptuator", "LRA"])
        device_select_layout.addWidget(self.actuator_combo)
        device_select_layout.addStretch()
        device_layout.addLayout(device_select_layout)
        
        device_group.setLayout(device_layout)
        layout.addWidget(device_group)
        
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
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'Magnitude', units='dB')
        self.plot_widget.setLabel('bottom', 'Frequency', units='Hz')
        self.plot_widget.setTitle('Transfer Function')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setMinimumHeight(400)
        self.plot_widget.setLogMode(x=True, y=False)
        
        # Configure plot appearance
        self.plot_widget.getPlotItem().getAxis('left').setPen(pg.mkPen(color='k', width=1))
        self.plot_widget.getPlotItem().getAxis('bottom').setPen(pg.mkPen(color='k', width=1))
        
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
            response = self.recording_interface.record_response(excitation)

            # Run characterization in thread
            self.characterization_worker = CharacterizationWorker(
                self.characterizer,
                excitation,
                response,
                self.actuator_combo.currentText(),
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
        
