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
    QDoubleSpinBox, QPlainTextEdit, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
import numpy as np
import pyqtgraph as pg
from processing.compensation import Compensator, CompensationFilter
from processing.characterization import ActuatorCharacterization
from resource_paths import bundled_path, user_data_path


class CompensationWidget(QWidget):
    """Widget for device compensation module."""
    
    compensation_updated = pyqtSignal(CompensationFilter)
    
    def __init__(self, sample_rate: int = 44100):
        super().__init__()
        self.sample_rate = sample_rate
        self.compensator = Compensator(sample_rate)
        self.current_characterization = None
        self.current_compensation = None
        self.generated_compensation = None
        self.current_signal = None
        self.setup_ui()
        self.refresh_filter_library()
    
    def setup_ui(self):
        """Setup UI elements."""
        layout = QVBoxLayout()
        
        # Workflow 1: generate from the preceding characterization step.
        input_group = QGroupBox("1. Generate from Characterization")
        input_layout = QVBoxLayout()
        input_layout.addWidget(
            QLabel("Create an inverse compensation from the actuator measurement in step 3.")
        )
        
        input_select_layout = QHBoxLayout()
        input_select_layout.addWidget(QLabel("Actuator Characterization:"))
        self.actuator_combo = QComboBox()
        self.actuator_combo.addItems(["No characterization"])
        input_select_layout.addWidget(self.actuator_combo)
        input_select_layout.addStretch()
        input_layout.addLayout(input_select_layout)
        
        # Compensation parameters
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
        
        input_layout.addLayout(params_layout)
        
        self.compute_button = QPushButton("Compute Compensation")
        self.compute_button.clicked.connect(self.compute_compensation)
        input_layout.addWidget(self.compute_button, 0, Qt.AlignmentFlag.AlignLeft)
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # Workflow 2: select the generated filter or a JSON preset.
        library_group = QGroupBox("2. Load an Existing Filter")
        library_layout = QVBoxLayout()
        library_layout.addWidget(
            QLabel(
                "Use the current generated filter, choose a preset from the compensation_filters "
                "folder, or browse for another JSON filter."
            )
        )
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Available filter:"))
        self.filter_library_combo = QComboBox()
        filter_row.addWidget(self.filter_library_combo, 1)

        self.use_filter_button = QPushButton("Use Selected")
        self.use_filter_button.clicked.connect(self.use_selected_filter)
        filter_row.addWidget(self.use_filter_button)

        self.refresh_filters_button = QPushButton("Refresh")
        self.refresh_filters_button.clicked.connect(self.refresh_filter_library)
        filter_row.addWidget(self.refresh_filters_button)
        library_layout.addLayout(filter_row)

        library_buttons = QHBoxLayout()
        self.load_button = QPushButton("Browse…")
        self.load_button.clicked.connect(self.load_compensation_file)
        library_buttons.addWidget(self.load_button)

        self.save_button = QPushButton("Save Current…")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_current_filter)
        library_buttons.addWidget(self.save_button)
        library_buttons.addStretch()
        library_layout.addLayout(library_buttons)
        library_group.setLayout(library_layout)
        layout.addWidget(library_group)
        
        # Spectrum display
        spectrum_group = QGroupBox("Compensation Effect")
        spectrum_layout = QVBoxLayout()
        
        self.spectrum_text = QPlainTextEdit()
        self.spectrum_text.setReadOnly(True)
        self.spectrum_text.setMaximumHeight(120)
        spectrum_layout.addWidget(self.spectrum_text)

        self.compensation_plot = pg.PlotWidget()
        self.compensation_plot.setBackground("#ffffff")
        self.compensation_plot.setLabel("left", "Magnitude", units="dB")
        self.compensation_plot.setLabel("bottom", "Frequency", units="Hz")
        self.compensation_plot.setTitle("Before and After Compensation")
        self.compensation_plot.setLogMode(x=True, y=False)
        self.compensation_plot.showGrid(x=True, y=True, alpha=0.25)
        self.compensation_plot.setMinimumHeight(180)
        plot_item = self.compensation_plot.getPlotItem()
        plot_item.getAxis("left").setPen(pg.mkPen(color="#617086", width=1))
        plot_item.getAxis("bottom").setPen(pg.mkPen(color="#617086", width=1))
        plot_item.getAxis("left").setTextPen("#263246")
        plot_item.getAxis("bottom").setTextPen("#263246")
        plot_item.addLegend()
        spectrum_layout.addWidget(self.compensation_plot, 1)
        
        spectrum_group.setLayout(spectrum_layout)
        layout.addWidget(spectrum_group)
        
        
        layout.addStretch()
        self.setLayout(layout)
    
    def set_characterization(self, characterization: ActuatorCharacterization):
        """Set actuator characterization."""
        self.current_characterization = characterization
        self.compute_button.setEnabled(True)
        self.actuator_combo.clear()
        self.actuator_combo.addItem(
            f"{characterization.actuator_name} ({characterization.excitation_type or 'measurement'})"
        )
        self.spectrum_text.setPlainText(
            f"Characterization loaded: {characterization.actuator_name}\n"
            f"Frequency bins: {len(characterization.frequencies)}\n"
            f"Sample rate: {getattr(characterization, 'sample_rate', self.sample_rate)} Hz"
        )

    def set_signal(self, signal_data: np.ndarray, sample_rate: int):
        """Set the workshop signal used for the before/after preview."""
        data = np.asarray(signal_data, dtype=np.float32)
        self.current_signal = data[:, 0] if data.ndim > 1 else data.reshape(-1)
        self.sample_rate = int(sample_rate)
        self.compensator.sample_rate = self.sample_rate
        if self.current_compensation is not None:
            self._update_compensation_plot()
    
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
            self.generated_compensation = self.current_compensation
            self.save_button.setEnabled(True)
            self.refresh_filter_library()
            
            # Update display
            self.update_display()
            self.compensation_updated.emit(self.current_compensation)
        except Exception as e:
            print(f"Error computing compensation: {e}")

    def load_compensation_file(self, filepath: str | None = None):
        """Load a JSON compensation, including zero-phase filtfilt filters."""
        if not filepath:
            filepath, _ = QFileDialog.getOpenFileName(
                self,
                "Load Compensation Filter",
                str(user_data_path("compensation_filters", create=True)),
                "Compensation filters (*.json);;All files (*)",
            )
        if not filepath:
            return
        try:
            self.current_compensation = self.compensator.load_filter(filepath)
            self.save_button.setEnabled(True)
            self.update_display()
            self.compensation_updated.emit(self.current_compensation)
        except Exception as exc:
            QMessageBox.critical(self, "Invalid Compensation Filter", str(exc))

    def refresh_filter_library(self):
        """List the in-memory generated filter and JSON files in the preset folder."""
        selected = self.filter_library_combo.currentData() if self.filter_library_combo.count() else None
        self.filter_library_combo.clear()
        if self.generated_compensation is not None:
            self.filter_library_combo.addItem(
                f"Current generated — {self.generated_compensation.name}",
                "__generated__",
            )

        filter_files = {}
        bundled_dir = bundled_path("compensation_filters")
        user_dir = user_data_path("compensation_filters", create=True)
        for filters_dir in (bundled_dir, user_dir):
            if filters_dir.exists():
                for filepath in filters_dir.glob("*.json"):
                    filter_files[filepath.name] = filepath
        for filepath in sorted(filter_files.values(), key=lambda item: item.name.lower()):
            try:
                filter_name = self.compensator.load_filter(str(filepath)).name
            except Exception:
                filter_name = f"{filepath.stem} (invalid)"
            self.filter_library_combo.addItem(f"{filter_name} — {filepath.name}", str(filepath))

        if self.filter_library_combo.count() == 0:
            self.filter_library_combo.addItem("No filters available", None)
        if selected is not None:
            index = self.filter_library_combo.findData(selected)
            if index >= 0:
                self.filter_library_combo.setCurrentIndex(index)
        self.use_filter_button.setEnabled(self.filter_library_combo.currentData() is not None)

    def use_selected_filter(self):
        """Activate the selected generated or folder-based compensation."""
        selection = self.filter_library_combo.currentData()
        if selection == "__generated__":
            self.current_compensation = self.generated_compensation
            self.save_button.setEnabled(True)
            self.update_display()
            self.compensation_updated.emit(self.current_compensation)
        elif selection:
            self.load_compensation_file(str(selection))

    def save_current_filter(self):
        """Save the active compensation into the shared filter folder or another location."""
        if self.current_compensation is None:
            return
        filters_dir = user_data_path("compensation_filters", create=True)
        default_name = (
            self.current_compensation.name.lower().replace(" ", "_").replace("–", "-")
            or "compensation_filter"
        )
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Save Compensation Filter",
            str(filters_dir / f"{default_name}.json"),
            "Compensation filters (*.json)",
        )
        if not filepath:
            return
        try:
            self.compensator.save_filter(filepath, self.current_compensation)
            self.refresh_filter_library()
        except Exception as exc:
            QMessageBox.critical(self, "Could Not Save Filter", str(exc))
    
    def update_display(self):
        """Update spectrum and displays."""
        if not self.current_compensation:
            return
        
        # Spectrum info
        spectrum_text = "Compensation Filter Response:\n"
        spectrum_text += f"Name: {self.current_compensation.name or 'Computed compensation'}\n"
        spectrum_text += f"Method: {self.current_compensation.application_method}\n"
        spectrum_text += f"Frequency Range: {self.current_compensation.frequencies[0]:.1f} Hz"
        spectrum_text += f" to {self.current_compensation.frequencies[-1]:.1f} Hz\n"
        
        max_mag = np.max(self.current_compensation.magnitude)
        min_mag = np.min(self.current_compensation.magnitude)
        spectrum_text += f"Magnitude Range: {min_mag:.2f} to {max_mag:.2f}\n"
        spectrum_text += f"Max Gain: {20*np.log10(max_mag):.1f} dB\n"
        
        self.spectrum_text.setPlainText(spectrum_text)
        self._update_compensation_plot()
        
        # Check for high gains
        gain_db = 20 * np.log10(self.current_compensation.magnitude + 1e-10)
        high_gain_freq = self.current_compensation.frequencies[np.argmax(gain_db)]
        
        # Check phase stability
        phase_unwrapped = np.unwrap(self.current_compensation.phase)
        max_phase_change = np.max(np.abs(np.diff(phase_unwrapped)))

    def _update_compensation_plot(self):
        """Plot the predicted actuator response before and after correction."""
        compensation = self.current_compensation
        if compensation is None:
            self.compensation_plot.clear()
            return

        frequencies = np.asarray(compensation.frequencies, dtype=np.float64)
        compensation_magnitude = np.asarray(compensation.magnitude, dtype=np.float64)
        valid = (
            np.isfinite(frequencies)
            & np.isfinite(compensation_magnitude)
            & (frequencies > 0)
        )
        frequencies = frequencies[valid]
        compensation_magnitude = compensation_magnitude[valid]
        if len(frequencies) == 0:
            self.compensation_plot.clear()
            return

        if self.current_signal is not None and len(self.current_signal) > 1:
            before_signal = np.asarray(self.current_signal, dtype=np.float64)
            after_signal = self.compensator.apply(before_signal, compensation)
            window = np.hanning(len(before_signal))
            frequencies = np.fft.rfftfreq(len(before_signal), 1.0 / self.sample_rate)
            before_magnitude = np.abs(np.fft.rfft(before_signal * window))
            after_magnitude = np.abs(np.fft.rfft(after_signal * window))
            valid = frequencies > 0
            frequencies = frequencies[valid]
            before_magnitude = before_magnitude[valid]
            after_magnitude = after_magnitude[valid]
            before_name = "Before: current signal"
            after_name = "After: compensated signal"
            self.compensation_plot.setTitle("Current Signal Before and After Compensation")
        elif self.current_characterization is not None:
            source_frequencies = np.asarray(
                self.current_characterization.frequencies,
                dtype=np.float64,
            )
            source_magnitude = np.asarray(
                self.current_characterization.magnitude,
                dtype=np.float64,
            )
            before_magnitude = np.interp(
                frequencies,
                source_frequencies,
                source_magnitude,
                left=source_magnitude[0],
                right=source_magnitude[-1],
            )
            before_name = "Before: actuator"
            after_name = "After: compensated actuator"
            after_magnitude = before_magnitude * compensation_magnitude
            self.compensation_plot.setTitle("Actuator Response Before and After Compensation")
        else:
            before_magnitude = np.ones_like(frequencies)
            before_name = "Before: no compensation"
            after_name = "After: loaded filter"
            after_magnitude = before_magnitude * compensation_magnitude
            self.compensation_plot.setTitle("Filter Response Before and After Compensation")
        floor = 1e-10
        before_db = 20.0 * np.log10(np.maximum(np.abs(before_magnitude), floor))
        after_db = 20.0 * np.log10(np.maximum(np.abs(after_magnitude), floor))

        plot_item = self.compensation_plot.getPlotItem()
        self.compensation_plot.clear()
        if plot_item.legend is not None:
            plot_item.legend.clear()
        self.compensation_plot.plot(
            frequencies,
            before_db,
            pen=pg.mkPen("#073f83", width=2),
            name=before_name,
        )
        self.compensation_plot.plot(
            frequencies,
            after_db,
            pen=pg.mkPen("#0aa9e8", width=2.5),
            name=after_name,
        )
        
