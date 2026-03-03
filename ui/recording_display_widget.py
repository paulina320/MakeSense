"""
Recording Display Widget
Displays waveform visualization of recorded/loaded recordings.
"""

import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QLabel
from PyQt6.QtCore import Qt
import pyqtgraph as pg
import numpy as np
from processing.recording import Recording


class RecordingDisplayWidget(QWidget):
    """Widget for displaying recorded waveforms."""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI elements."""
        layout = QVBoxLayout()
        
        # Waveform display group
        display_group = QGroupBox("Waveform Display")
        display_layout = QVBoxLayout()
        
        # Info label
        self.info_label = QLabel("No recording loaded")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        display_layout.addWidget(self.info_label)
        
        # Setup pyqtgraph plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', 'Amplitude')
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_widget.setTitle('Recorded Signal')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setMinimumHeight(300)
        
        # Configure plot appearance
        self.plot_widget.getPlotItem().getAxis('left').setPen(pg.mkPen(color='k', width=1))
        self.plot_widget.getPlotItem().getAxis('bottom').setPen(pg.mkPen(color='k', width=1))
        
        display_layout.addWidget(self.plot_widget)
        
        display_group.setLayout(display_layout)
        layout.addWidget(display_group)
        
        self.setLayout(layout)
    
    def update_display(self, recording: Recording):
        """
        Update the display with new recording data.
        
        Args:
            recording: Recording object containing data and metadata
        """
        if recording is None or recording.data is None:
            self.clear_display()
            return
        
        # Clear previous plot
        self.plot_widget.clear()
        
        # Create time axis
        duration = len(recording.data) / recording.sample_rate
        time = np.linspace(0, duration, len(recording.data))
        
        # Plot waveform
        pen = pg.mkPen(color='b', width=1)
        self.plot_widget.plot(time, recording.data, pen=pen)
        
        # Update info label
        num_samples = len(recording.data)
        info_text = (
            f"Sample Rate: {recording.sample_rate} Hz | "
            f"Duration: {duration:.2f} s | "
            f"Samples: {num_samples}"
        )
        self.info_label.setText(info_text)
    
    def clear_display(self):
        """Clear the display."""
        self.plot_widget.clear()
        self.info_label.setText("No recording loaded")
    
    def load_from_file(self, file_path: str):
        """
        Load and display recording from file.
        
        Args:
            file_path: Path to the recording file
        """
        from data import FileIO
        
        try:
            file_io = FileIO()
            
            if file_path.endswith('.npz'):
                recording = file_io.load_npz(file_path)
            elif file_path.endswith('.wav'):
                data, sample_rate = file_io.load_wav(file_path)
                recording = Recording(data, sample_rate)
            elif file_path.endswith('.csv'):
                data = file_io.load_csv(file_path)
                # Default sample rate if not specified
                recording = Recording(data, 44100)
            else:
                self.info_label.setText("Unsupported file format")
                return
            
            self.update_display(recording)
            
        except Exception as e:
            self.info_label.setText(f"Error loading file: {str(e)}")
