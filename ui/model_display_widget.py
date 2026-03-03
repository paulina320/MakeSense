"""
Model Display Widget
Displays FFT comparison between original and modeled signals.
"""

import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel
from PyQt6.QtCore import Qt
import pyqtgraph as pg
import numpy as np
from processing.fft_tools import compute_fft


class ModelDisplayWidget(QWidget):
    """Widget for displaying FFT comparison of original vs modeled signals."""
    
    def __init__(self):
        super().__init__()
        self.original_data = None
        self.original_sample_rate = None
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI elements."""
        layout = QVBoxLayout()
        
        # FFT display group
        display_group = QGroupBox("FFT Comparison")
        display_layout = QVBoxLayout()
        
        # Info label
        self.info_label = QLabel("No recording loaded")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        display_layout.addWidget(self.info_label)
        
        # Setup pyqtgraph plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'Magnitude', units='dB')
        self.plot_widget.setLabel('bottom', 'Frequency', units='Hz')
        self.plot_widget.setTitle('FFT Spectrum Comparison')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setMinimumHeight(400)
        self.plot_widget.setLogMode(x=True, y=False)
        
        # Configure plot appearance
        self.plot_widget.getPlotItem().getAxis('left').setPen(pg.mkPen(color='k', width=1))
        self.plot_widget.getPlotItem().getAxis('bottom').setPen(pg.mkPen(color='k', width=1))
        
        # Add legend
        self.plot_widget.addLegend()
        
        display_layout.addWidget(self.plot_widget)
        
        display_group.setLayout(display_layout)
        layout.addWidget(display_group)
        
        self.setLayout(layout)
    
    def set_original_recording(self, data: np.ndarray, sample_rate: int):
        """
        Set the original recording and display its FFT.
        
        Args:
            data: Original signal data
            sample_rate: Sample rate in Hz
        """
        self.original_data = data
        self.original_sample_rate = sample_rate
        
        # Clear and plot original FFT
        self.plot_widget.clear()
        
        # Compute FFT
        freqs, mag_db = compute_fft(data, sample_rate, fft_size=4096)
        
        # Plot original
        pen_original = pg.mkPen(color='b', width=2)
        self.plot_widget.plot(freqs, mag_db, pen=pen_original, name='Original')
        
        # Update info
        self.info_label.setText(f"Original Signal | Sample Rate: {sample_rate} Hz")
    
    def update_model_display(self, reconstructed_data: np.ndarray, model_name: str):
        """
        Update display with modeled signal FFT.
        
        Args:
            reconstructed_data: Reconstructed signal from model
            model_name: Name of the model used
        """
        if self.original_data is None:
            return
        
        # Clear previous plots
        self.plot_widget.clear()
        
        # Plot original FFT
        freqs_orig, mag_db_orig = compute_fft(self.original_data, self.original_sample_rate, fft_size=4096)
        pen_original = pg.mkPen(color='b', width=2)
        self.plot_widget.plot(freqs_orig, mag_db_orig, pen=pen_original, name='Original')
        
        # Plot reconstructed FFT
        freqs_recon, mag_db_recon = compute_fft(reconstructed_data, self.original_sample_rate, fft_size=4096)
        pen_recon = pg.mkPen(color='r', width=2)
        self.plot_widget.plot(freqs_recon, mag_db_recon, pen=pen_recon, name=f'{model_name} Model')
        
        # Update info
        self.info_label.setText(f"Model: {model_name} | Sample Rate: {self.original_sample_rate} Hz")
    
    def clear_display(self):
        """Clear the display."""
        self.plot_widget.clear()
        self.info_label.setText("No recording loaded")
        self.original_data = None
        self.original_sample_rate = None
