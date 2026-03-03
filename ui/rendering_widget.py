"""
Rendering Widget
UI for texture rendering and playback module.
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
    QCheckBox, QPlainTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
import numpy as np
from processing.rendering import Renderer, RenderSettings, PlaybackController
from processing.recording import Recording


class RenderingWidget(QWidget):
    """Widget for rendering and playback module."""
    
    playback_started = pyqtSignal()
    playback_stopped = pyqtSignal()
    
    def __init__(self, sample_rate: int = 44100):
        super().__init__()
        self.sample_rate = sample_rate
        self.renderer = Renderer(sample_rate)
        self.playback_controller = PlaybackController(sample_rate)
        self.current_recording = None
        self.current_characterization = None
        self.current_compensation = None
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI elements."""
        layout = QVBoxLayout()
        
        # Configuration
        config_group = QGroupBox("Rendering Configuration")
        config_layout = QVBoxLayout()
        
        # Model selection
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems([
            "Raw Signal",
            "Spectral Envelope",
            "Reduced Parameters",
            "Filter-Based"
        ])
        model_layout.addWidget(self.model_combo)
        model_layout.addStretch()
        config_layout.addLayout(model_layout)
        
        # Actuator selection
        actuator_layout = QHBoxLayout()
        actuator_layout.addWidget(QLabel("Actuator:"))
        self.actuator_combo = QComboBox()
        self.actuator_combo.addItems(["None", "Haptuator", "LRA"])
        actuator_layout.addWidget(self.actuator_combo)
        actuator_layout.addStretch()
        config_layout.addLayout(actuator_layout)
        
        # Apply compensation
        comp_layout = QHBoxLayout()
        self.compensation_check = QCheckBox("Apply Compensation")
        comp_layout.addWidget(self.compensation_check)
        comp_layout.addStretch()
        config_layout.addLayout(comp_layout)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # Playback controls
        playback_group = QGroupBox("Playback Control")
        playback_layout = QVBoxLayout()
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.start_playback)
        button_layout.addWidget(self.play_button)
        
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.pause_playback)
        self.pause_button.setEnabled(False)
        button_layout.addWidget(self.pause_button)
        
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_playback)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)
        
        self.loop_check = QCheckBox("Loop")
        button_layout.addWidget(self.loop_check)
        
        button_layout.addStretch()
        playback_layout.addLayout(button_layout)
        
        # Volume control
        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("Volume (dB):"))
        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setMinimum(-60)
        self.volume_slider.setMaximum(20)
        self.volume_slider.setValue(-3)
        self.volume_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        volume_layout.addWidget(self.volume_slider)
        
        self.volume_label = QLabel("-3 dB")
        volume_layout.addWidget(self.volume_label)
        playback_layout.addLayout(volume_layout)
        
        playback_group.setLayout(playback_layout)
        layout.addWidget(playback_group)
        
        # Output monitoring
        monitor_group = QGroupBox("Output Monitoring")
        monitor_layout = QVBoxLayout()
        
        button_layout = QHBoxLayout()
        self.render_button = QPushButton("Render & Analyze")
        self.render_button.clicked.connect(self.render_and_analyze)
        button_layout.addWidget(self.render_button)
        
        self.spectrum_button = QPushButton("Show Spectrum")
        button_layout.addWidget(self.spectrum_button)
        
        button_layout.addStretch()
        monitor_layout.addLayout(button_layout)
        
        # Info display
        self.info_text = QPlainTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(100)
        monitor_layout.addWidget(self.info_text)
        
        monitor_group.setLayout(monitor_layout)
        layout.addWidget(monitor_group)
        
        # Status display
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()
        
        self.status_text = QPlainTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(80)
        status_layout.addWidget(self.status_text)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # Timer for playback status updates
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_playback_status)
    
    def set_recording(self, recording: Recording):
        """Set current recording for rendering."""
        self.current_recording = recording
    
    def set_characterization(self, characterization):
        """Set actuator characterization."""
        self.current_characterization = characterization
    
    def set_compensation(self, compensation):
        """Set compensation filter."""
        self.current_compensation = compensation
    
    def render_and_analyze(self):
        """Render signal and analyze output."""
        if not self.current_recording:
            self.status_text.setPlainText("No recording loaded")
            return
        
        try:
            # Determine model
            model_names = {
                "Raw Signal": "raw",
                "Spectral Envelope": "spectral",
                "Reduced Parameters": "reduced",
                "Filter-Based": "filter"
            }
            model_type = model_names.get(self.model_combo.currentText(), "raw")
            
            from processing.texture_models import create_texture_model
            model = create_texture_model(model_type)
            
            # Render
            rendered = self.renderer.render(
                self.current_recording,
                model,
                gain_db=self.volume_slider.value(),
                apply_actuator_response=(self.actuator_combo.currentText() != "None"),
                actuator=self.current_characterization,
                apply_compensation=self.compensation_check.isChecked(),
                compensation=self.current_compensation,
            )
            
            # Load into playback
            self.playback_controller.load_texture(rendered)
            
            # Get spectrum
            freqs, mag_db = self.renderer.get_output_spectrum(rendered)
            
            # Update info
            info_text = f"Rendered: {len(rendered)} samples ({len(rendered)/self.sample_rate:.2f}s)\n"
            info_text += f"RMS Level: {np.sqrt(np.mean(rendered**2)):.3f}\n"
            info_text += f"Peak Level: {np.max(np.abs(rendered)):.3f}\n"
            info_text += f"Spectrum: {freqs[0]:.1f} - {freqs[-1]:.1f} Hz"
            
            self.info_text.setPlainText(info_text)
            self.play_button.setEnabled(True)
            self.status_text.setPlainText("Ready for playback")
        except Exception as e:
            self.status_text.setPlainText(f"Error: {str(e)}")
    
    def start_playback(self):
        """Start playback."""
        if self.current_recording is None:
            self.render_and_analyze()
        
        self.playback_controller.set_loop(self.loop_check.isChecked())
        self.playback_controller.start()
        
        self.play_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.status_text.setPlainText("Playback: PLAYING")
        
        self.status_timer.start(100)
        self.playback_started.emit()
    
    def pause_playback(self):
        """Pause playback."""
        self.playback_controller.pause()
        
        self.play_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.status_text.setPlainText("Playback: PAUSED")
    
    def stop_playback(self):
        """Stop playback."""
        self.playback_controller.stop()
        
        self.play_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.status_text.setPlainText("Playback: STOPPED")
        
        self.status_timer.stop()
        self.playback_stopped.emit()
    
    def on_volume_changed(self):
        """Handle volume slider change."""
        db = self.volume_slider.value()
        self.volume_label.setText(f"{db} dB")
        if self.playback_controller.playback_data is not None:
            self.playback_controller.set_gain(db)
    
    def update_playback_status(self):
        """Update playback status display."""
        if self.playback_controller.is_playing:
            pos = self.playback_controller.current_position
            total = len(self.playback_controller.playback_data) if self.playback_controller.playback_data else 1
            progress = int(100 * pos / total)
            time_s = pos / self.sample_rate if self.sample_rate > 0 else 0
            self.status_text.setPlainText(f"Playback: {progress}% ({time_s:.2f}s)")
