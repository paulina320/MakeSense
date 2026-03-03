"""
Main Application Window
Central hub for the haptic software application.
"""

import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QTabWidget,
    QStatusBar, QMenuBar, QMenu, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QKeySequence

from ui import (
    RecordingWidget,
    ModelWidget,
    CharacterizationWidget,
    CompensationWidget,
    RenderingWidget,
)
from processing.recording import Recording
from data import ProjectManager, FileIO
from hardware import create_daq_interface
from config import config


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.UI_CONFIG["app_name"])
        self.setGeometry(100, 100, config.UI_CONFIG["window_width"], config.UI_CONFIG["window_height"])
        
        # Initialize components
        self.project_manager = ProjectManager()
        self.current_recording = None
        self.current_characterization = None
        self.current_compensation = None
        
        # Create audio interface
        try:
            self.recording_interface = create_daq_interface("mock")
        except ImportError:
            self.recording_interface = None
        
        # Setup UI
        self.setup_menu()
        self.setup_widgets()
        self.setup_status()
        
        self.statusBar().showMessage("Ready")
    
    def setup_menu(self):
        """Setup menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        new_project_action = file_menu.addAction("&New Project...")
        new_project_action.setShortcut(QKeySequence.StandardKey.New)
        new_project_action.triggered.connect(self.new_project)
        
        open_project_action = file_menu.addAction("&Open Project...")
        open_project_action.setShortcut(QKeySequence.StandardKey.Open)
        open_project_action.triggered.connect(self.open_project)
        
        file_menu.addSeparator()
        
        save_project_action = file_menu.addAction("&Save Project")
        save_project_action.setShortcut(QKeySequence.StandardKey.Save)
        save_project_action.triggered.connect(self.save_project)
        
        file_menu.addSeparator()
        
        exit_action = file_menu.addAction("E&xit")
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
                
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self.show_about)
        
        documentation_action = help_menu.addAction("&Documentation")
        documentation_action.triggered.connect(self.show_documentation)
    
    def setup_widgets(self):
        """Setup main widget tabs."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # Create tab widget
        self.tabs = QTabWidget()
        
        # Create module widgets
        self.recording_widget = RecordingWidget(self.recording_interface)
        self.recording_widget.recording_complete.connect(self.on_recording_complete)
        
        self.model_widget = ModelWidget()
        self.model_widget.model_updated.connect(self.on_model_updated)
        
        self.characterization_widget = CharacterizationWidget(self.recording_interface)
        self.characterization_widget.characterization_complete.connect(self.on_characterization_complete)
        
        self.compensation_widget = CompensationWidget()
        self.compensation_widget.compensation_updated.connect(self.on_compensation_updated)
        
        self.rendering_widget = RenderingWidget()
        self.rendering_widget.playback_started.connect(self.on_playback_started)
        self.rendering_widget.playback_stopped.connect(self.on_playback_stopped)
    
        # Add tabs
        self.tabs.addTab(self.recording_widget, "1. Recording")
        self.tabs.addTab(self.model_widget, "2. Texture Model")
        self.tabs.addTab(self.characterization_widget, "3. Characterization")
        self.tabs.addTab(self.compensation_widget, "4. Compensation")
        self.tabs.addTab(self.rendering_widget, "5. Rendering")
        
        layout.addWidget(self.tabs)
        central_widget.setLayout(layout)
    
    def setup_status(self):
        """Setup status bar."""
        self.statusBar().showMessage("Ready")
    
    # File operations
    
    def new_project(self):
        """Create new project."""
        from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QTextEdit, QDialogButtonBox, QVBoxLayout
        
        dialog = QDialog(self)
        dialog.setWindowTitle("New Project")
        dialog.setGeometry(200, 200, 400, 300)
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel("Project Name:"))
        name_input = QLineEdit()
        layout.addWidget(name_input)
        
        layout.addWidget(QLabel("Description:"))
        desc_input = QTextEdit()
        desc_input.setMaximumHeight(100)
        layout.addWidget(desc_input)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        dialog.setLayout(layout)
        
        if dialog.exec():
            project_name = name_input.text()
            description = desc_input.toPlainText()
            
            try:
                self.project_manager.create_project(project_name, description=description)
                self.statusBar().showMessage(f"Created project: {project_name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create project: {e}")
    
    def open_project(self):
        """Open existing project."""
        projects = self.project_manager.list_projects()
        
        if not projects:
            QMessageBox.information(self, "No Projects", "No projects found. Create one first.")
            return
        
        # Simple selection (would be improved with a dialog)
        project_name = projects[0]
        
        try:
            self.project_manager.open_project(str(self.project_manager.project_base_dir / project_name))
            self.statusBar().showMessage(f"Opened project: {project_name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open project: {e}")
 
    
    def save_project(self):
        """Save current project state."""
        if self.project_manager.current_project is None:
            QMessageBox.warning(self, "No Project", "No project open")
            return
        
        try:
            state = {
                "recording": self.current_recording is not None,
                "characterization": self.current_characterization is not None,
                "compensation": self.current_compensation is not None,
            }
            
            self.project_manager.save_session_state(state)
            self.statusBar().showMessage("Project saved")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save project: {e}")
    
    # Signal handlers
    
    def on_recording_complete(self, recording: Recording):
        """Handle recording completion."""
        self.current_recording = recording
        self.model_widget.set_recording(recording)
        self.rendering_widget.set_recording(recording)
        
        self.statusBar().showMessage(
            f"Recording: {recording.duration:.2f}s @ {recording.sample_rate} Hz"
        )
        
        # Move to next tab
        # self.tabs.setCurrentIndex(1)
    
    def on_model_updated(self, parameters):
        """Handle model parameter update."""
        self.statusBar().showMessage("Model updated")
    
    def on_characterization_complete(self, characterization):
        """Handle characterization completion."""
        self.current_characterization = characterization
        self.compensation_widget.set_characterization(characterization)
        self.rendering_widget.set_characterization(characterization)
        
        self.statusBar().showMessage(
            f"Characterized: {characterization.actuator_name}"
        )
        
        # Move to next tab
        # self.tabs.setCurrentIndex(3)
    
    def on_compensation_updated(self, compensation):
        """Handle compensation filter update."""
        self.current_compensation = compensation
        self.rendering_widget.set_compensation(compensation)
        
        self.statusBar().showMessage("Compensation filter computed")
    
    def on_playback_started(self):
        """Handle playback start."""
        self.statusBar().showMessage("Playback started")
    
    def on_playback_stopped(self):
        """Handle playback stop."""
        self.statusBar().showMessage("Playback stopped")
    
    #TODO: implement this
    def show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Haptic Software",
            f"{config.UI_CONFIG['app_name']}\n\n"
            "A comprehensive application for haptic texture recording,\n"
            "modeling, characterization, and rendering. created for the EuroHaptics 2026 Workshop by the HITLab\n\n"
            "Version: 1.0"
        )
    
    #TODO: implement this
    def show_documentation(self):
        """Show documentation."""
        QMessageBox.information(
            self,
            "Documentation",
            "Complete documentation is available at:\n"
            "TODO"
        )
