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
        self._live_curves = []
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI elements."""
        layout = QVBoxLayout()
        
        # Waveform display group
        display_group = QGroupBox("Waveform Display")
        display_layout = QVBoxLayout()
        
        # Info label
        self.info_label = QLabel("No recording loaded")
        self.info_label.setStyleSheet("font-weight: 600; font-size: 14px; color: #ef6673;")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        display_layout.addWidget(self.info_label)
        
        # Setup pyqtgraph plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#ffffff")
        self.plot_widget.setLabel('left', 'Amplitude')
        self.plot_widget.setLabel('bottom', 'Time', units='s')
        self.plot_widget.setTitle('Recorded Signal')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setMinimumHeight(150)
        
        # Configure plot appearance
        self.plot_widget.getPlotItem().getAxis('left').setPen(pg.mkPen(color="#617086", width=1))
        self.plot_widget.getPlotItem().getAxis('bottom').setPen(pg.mkPen(color="#617086", width=1))
        self.plot_widget.getPlotItem().getAxis('left').setTextPen("#263246")
        self.plot_widget.getPlotItem().getAxis('bottom').setTextPen("#263246")
        
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
        plot_item = self.plot_widget.getPlotItem()
        if plot_item.legend is not None:
            plot_item.legend.scene().removeItem(plot_item.legend)
            plot_item.legend = None
        self.plot_widget.clear()
        self._live_curves = []
        
        # Create time axis
        duration = len(recording.data) / recording.sample_rate
        time = np.arange(len(recording.data)) / recording.sample_rate
        
        # Plot waveform
        data = np.asarray(recording.data)
        if data.ndim == 1:
            data = data.reshape(-1, 1)

        channel_names = getattr(recording.metadata, "channel_names", None) or []
        colors = ['b', 'r', 'g', 'm', 'c', 'y', 'k', (255, 128, 0), (128, 0, 255), (0, 128, 128)]
        if data.shape[1] > 1:
            self.plot_widget.addLegend()
        for channel_index in range(data.shape[1]):
            name = channel_names[channel_index] if channel_index < len(channel_names) else f"Input {channel_index + 1}"
            pen = pg.mkPen(color=colors[channel_index % len(colors)], width=1)
            self.plot_widget.plot(time, data[:, channel_index], pen=pen, name=name)
        
        # Update info label
        num_samples = len(recording.data)
        info_text = (
            f"Sample Rate: {recording.sample_rate} Hz | "
            f"Duration: {duration:.2f} s | "
            f"Samples: {num_samples} | "
            f"Inputs: {recording.num_channels}"
        )
        self.info_label.setText(info_text)
        self.info_label.setStyleSheet("font-weight: normal; font-size: 14px; color: #263246;")

    def update_live_data(
        self,
        data: np.ndarray,
        sample_rate: int,
        channel_names: list[str],
        first_sample: int = 0,
    ):
        """Update persistent plot curves with the latest acquisition window."""
        values = np.asarray(data)
        if values.ndim == 1:
            values = values.reshape(-1, 1)
        if values.size == 0:
            return

        colors = ['b', 'r', 'g', 'm', 'c', 'y', 'k', (255, 128, 0), (128, 0, 255), (0, 128, 128)]
        if len(self._live_curves) != values.shape[1]:
            plot_item = self.plot_widget.getPlotItem()
            if plot_item.legend is not None:
                plot_item.legend.scene().removeItem(plot_item.legend)
                plot_item.legend = None
            self.plot_widget.clear()
            self._live_curves = []
            if values.shape[1] > 1:
                self.plot_widget.addLegend()
            for channel_index in range(values.shape[1]):
                name = (
                    channel_names[channel_index]
                    if channel_index < len(channel_names)
                    else f"Input {channel_index + 1}"
                )
                self._live_curves.append(
                    self.plot_widget.plot(
                        pen=pg.mkPen(color=colors[channel_index % len(colors)], width=1),
                        name=name,
                    )
                )

        time_axis = (first_sample + np.arange(len(values), dtype=np.float64)) / max(1, sample_rate)
        for channel_index, curve in enumerate(self._live_curves):
            curve.setData(time_axis, values[:, channel_index])

        self.info_label.setText(
            f"Live | Sample Rate: {sample_rate} Hz | "
            f"Elapsed: {(first_sample + len(values)) / max(1, sample_rate):.2f} s | "
            f"Displayed: {len(values)} samples | Inputs: {values.shape[1]}"
        )
        self.info_label.setStyleSheet("font-weight: normal; font-size: 14px; color: #263246;")


    def clear_display(self):
        """Clear the display."""
        plot_item = self.plot_widget.getPlotItem()
        if plot_item.legend is not None:
            plot_item.legend.scene().removeItem(plot_item.legend)
            plot_item.legend = None
        self.plot_widget.clear()
        self._live_curves = []
        self.info_label.setText("No recording loaded")
        self.info_label.setStyleSheet("font-weight: 600; font-size: 14px; color: #ef6673;")

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
                recording = file_io.load_recording(file_path, "npz")
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
