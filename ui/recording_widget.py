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
    QLabel, QTextEdit, QProgressBar, QFileDialog, QMessageBox, QInputDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
import numpy as np
from processing.recording import Recording, RecordingMetadata
from data import FileIO
from ui.recording_display_widget import RecordingDisplayWidget
import time

#TODO: actually make this wrapper interact with recording interface
class RecordingWorker(QThread):
    """Worker thread for non-blocking recording."""
    
    progress = pyqtSignal(int)
    finished = pyqtSignal(np.ndarray, int)  # data, sample_rate
    error = pyqtSignal(str)
    
    def __init__(self, duration: float, sample_rate: int, recording_interface):
        super().__init__()
        self.duration = duration
        self.sample_rate = sample_rate
        self.recording_interface = recording_interface
    
    def run(self):
        """Run recording in thread."""
        try:
            
            num_samples = int(self.duration * self.sample_rate)
            steps = 100
            step_duration = self.duration / steps
            
            for i in range(steps):
                if self.isInterruptionRequested():
                    break
                
                time.sleep(step_duration)
                self.progress.emit(i + 1)
            
            # Generate mock data
            data = np.random.randn(num_samples)
            self.finished.emit(data, self.sample_rate)
        except Exception as e:
            self.error.emit(str(e))


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
        self.sample_rate_spinbox.setMinimum(8000)
        self.sample_rate_spinbox.setMaximum(192000)
        self.sample_rate_spinbox.setValue(44100)
        self.sample_rate_spinbox.setSingleStep(8000)
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
        
        duration = self.duration_spinbox.value()
        sample_rate = self.sample_rate_spinbox.value()
        
        self.recording_worker = RecordingWorker(duration, sample_rate, self.recording_interface)
        self.recording_worker.progress.connect(self.on_recording_progress)
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
    
    def on_recording_finished(self, data: np.ndarray, sample_rate: int):
        """Handle recording completion."""
        
        recording = Recording(data, sample_rate)
        self.current_recording = recording  # Store for saving
        self.recording_complete.emit(recording)
        
        # Update display with new recording
        self.display_widget.update_display(recording)
        
        self.record_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.save_button.setEnabled(True)  # Enable save button after recording
        self.progress_bar.setVisible(False)
    
    def on_recording_error(self, error: str):
        """Handle recording error."""
        print(f"Recording error: {error}")
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
                file_io.save_wav(file_path, self.current_recording.data, self.current_recording.sample_rate)
            elif file_path.endswith('.csv'):
                file_io.save_csv(file_path, self.current_recording.data)
            elif file_path.endswith('.npz'):
                file_io.save_npz(file_path, self.current_recording)
            
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
                recording = file_io.load_npz(file_path)
            elif file_path.endswith('.wav'):
                data, sample_rate = file_io.load_wav(file_path)
                recording = Recording(data, sample_rate)
            elif file_path.endswith('.csv'):
                data = file_io.load_csv(file_path)
                # Default sample rate if not specified
                sample_rate, ok = QInputDialog.getInt(
                    self, "Sample Rate", "Enter sample rate (Hz):",
                    10000
                )
                if not ok:
                    return
                recording = Recording(data, sample_rate=sample_rate)
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
