"""
Compensation Widget
UI for device compensation module.
"""

import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QComboBox, QSlider, QLabel,
    QDoubleSpinBox, QPlainTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal
import numpy as np
from processing.compensation import Compensator, CompensationFilter
from processing.characterization import ActuatorCharacterization


class CompensationWidget(QWidget):
    """Widget for device compensation module."""
    
    compensation_updated = pyqtSignal(CompensationFilter)
    
    def __init__(self, sample_rate: int = 44100):
        super().__init__()
        self.sample_rate = sample_rate
        self.compensator = Compensator(sample_rate)
        self.current_characterization = None
        self.current_compensation = None
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI elements."""
        layout = QVBoxLayout()
        
        # Input selection
        input_group = QGroupBox("Input Selection")
        input_layout = QVBoxLayout()
        
        input_select_layout = QHBoxLayout()
        input_select_layout.addWidget(QLabel("Actuator Characterization:"))
        self.actuator_combo = QComboBox()
        self.actuator_combo.addItems(["Load Characterization...", "Haptuator Char 1", "LRA Char 1"])
        input_select_layout.addWidget(self.actuator_combo)
        input_select_layout.addStretch()
        input_layout.addLayout(input_select_layout)
        
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)
        
        # Compensation parameters
        params_group = QGroupBox("Compensation Parameters")
        params_layout = QVBoxLayout()
        
        # Regularization
        reg_layout = QHBoxLayout()
        reg_layout.addWidget(QLabel("Regularization:"))
        self.reg_slider = QSlider(Qt.Orientation.Horizontal)
        self.reg_slider.setMinimum(-10)
        self.reg_slider.setMaximum(0)
        self.reg_slider.setValue(-6)
        self.reg_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.reg_slider.valueChanged.connect(self.on_regularization_changed)
        reg_layout.addWidget(self.reg_slider)
        
        self.reg_label = QLabel("1e-6")
        reg_layout.addWidget(self.reg_label)
        params_layout.addLayout(reg_layout)
        
        # Max gain
        gain_layout = QHBoxLayout()
        gain_layout.addWidget(QLabel("Max Gain (dB):"))
        self.max_gain_spinbox = QDoubleSpinBox()
        self.max_gain_spinbox.setMinimum(0)
        self.max_gain_spinbox.setMaximum(60)
        self.max_gain_spinbox.setValue(20)
        self.max_gain_spinbox.setSingleStep(1)
        self.max_gain_spinbox.valueChanged.connect(self.compute_compensation)
        gain_layout.addWidget(self.max_gain_spinbox)
        gain_layout.addStretch()
        params_layout.addLayout(gain_layout)
        
        params_group.setLayout(params_layout)
        layout.addWidget(params_group)
        
        # Control buttons
        control_layout = QHBoxLayout()
        
        self.compute_button = QPushButton("Compute Compensation")
        self.compute_button.clicked.connect(self.compute_compensation)
        control_layout.addWidget(self.compute_button)
        
        self.apply_button = QPushButton("Apply Compensation")
        self.apply_button.setEnabled(False)
        control_layout.addWidget(self.apply_button)
        
        self.save_button = QPushButton("Save Filter")
        self.save_button.setEnabled(False)
        control_layout.addWidget(self.save_button)
        
        control_layout.addStretch()
        layout.addLayout(control_layout)
        
        # Spectrum display
        spectrum_group = QGroupBox("Compensation Effect")
        spectrum_layout = QVBoxLayout()
        
        self.spectrum_text = QPlainTextEdit()
        self.spectrum_text.setReadOnly(True)
        self.spectrum_text.setMaximumHeight(120)
        spectrum_layout.addWidget(self.spectrum_text)
        
        spectrum_group.setLayout(spectrum_layout)
        layout.addWidget(spectrum_group)
        
        
        layout.addStretch()
        self.setLayout(layout)
    
    def set_characterization(self, characterization: ActuatorCharacterization):
        """Set actuator characterization."""
        self.current_characterization = characterization
        self.compute_button.setEnabled(True)
    
    def on_regularization_changed(self):
        """Handle regularization slider change."""
        value = self.reg_slider.value()
        reg = 10 ** value
        self.reg_label.setText(f"{reg:.1e}")
        self.compute_compensation()
    
    def compute_compensation(self):
        """Compute compensation filter."""
        if not self.current_characterization:
            return
        
        try:
            # Compute inverse filter
            regularization = 10 ** self.reg_slider.value()
            max_gain_db = self.max_gain_spinbox.value()
            
            self.current_compensation = self.compensator.compute_inverse_filter(
                self.current_characterization,
                regularization=regularization,
                max_gain_db=max_gain_db,
            )
            
            self.apply_button.setEnabled(True)
            self.save_button.setEnabled(True)
            
            # Update display
            self.update_display()
            self.compensation_updated.emit(self.current_compensation)
        except Exception as e:
            print(f"Error computing compensation: {e}")
    
    def update_display(self):
        """Update spectrum and displays."""
        if not self.current_compensation:
            return
        
        # Spectrum info
        spectrum_text = "Compensation Filter Response:\n"
        spectrum_text += f"Frequency Range: {self.current_compensation.frequencies[0]:.1f} Hz"
        spectrum_text += f" to {self.current_compensation.frequencies[-1]:.1f} Hz\n"
        
        max_mag = np.max(self.current_compensation.magnitude)
        min_mag = np.min(self.current_compensation.magnitude)
        spectrum_text += f"Magnitude Range: {min_mag:.2f} to {max_mag:.2f}\n"
        spectrum_text += f"Max Gain: {20*np.log10(max_mag):.1f} dB\n"
        
        self.spectrum_text.setPlainText(spectrum_text)
        
        # Check for high gains
        gain_db = 20 * np.log10(self.current_compensation.magnitude + 1e-10)
        high_gain_freq = self.current_compensation.frequencies[np.argmax(gain_db)]
        
        # Check phase stability
        phase_unwrapped = np.unwrap(self.current_compensation.phase)
        max_phase_change = np.max(np.abs(np.diff(phase_unwrapped)))
        
