"""
Main Application Window
Central hub for the haptic software application.
"""

import sys
from io import BytesIO
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QTabWidget, QTabBar,
    QMessageBox, QStylePainter, QStyleOptionTab, QStyle, QScrollArea,
    QDialog, QLabel, QPushButton
)
from PyQt6.QtCore import Qt, QSize, QUrl
from PyQt6.QtGui import QKeySequence, QColor, QDesktopServices, QIcon, QPixmap

from ui import (
    RecordingWidget,
    ModelWidget,
    CharacterizationWidget,
    CompensationWidget,
    RenderingWidget,
    DeviceStatusWidget,
    DeviceConnectedWidget
)
from processing.recording import Recording
from hardware import create_daq_interface
from config import config

DOCUMENTATION_URL = "https://github.com/paulina320/MakeSense"


class WorkshopTabBar(QTabBar):
    """Horizontal labels in a PyDracula-style vertical navigation rail."""

    def tabSizeHint(self, index: int) -> QSize:
        return QSize(210, 58)

    def paintEvent(self, event):
        painter = QStylePainter(self)
        for index in range(self.count()):
            option = QStyleOptionTab()
            self.initStyleOption(option, index)
            text = option.text
            option.text = ""
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabShape, option)
            icon_rect = self.tabRect(index).adjusted(20, 0, 0, 0)
            icon_rect.setWidth(30)
            icon_rect.setHeight(30)
            icon_rect.moveCenter(
                self.tabRect(index).center() - self.tabRect(index).center() + icon_rect.center()
            )
            icon_rect.moveTop(self.tabRect(index).center().y() - 15)
            option.icon.paint(painter, icon_rect)
            painter.setPen(QColor("#ffffff" if index == self.currentIndex() else "#dcecf8"))
            painter.drawText(
                self.tabRect(index).adjusted(60, 0, -10, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.UI_CONFIG["app_name"])
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "icons" / "makesense.svg")))
        self.setGeometry(100, 100, config.UI_CONFIG["window_width"], config.UI_CONFIG["window_height"])
        
        # Initialize components
        self.current_recording = None
        self.current_model = None
        self.current_characterization = None
        self.current_compensation = None
        
        # Create hardware interface
        try:
            backend = config.HAPTIC_DEVICE_CONFIG.get(
                "backend",
                config.HARDWARE_CONFIG.get("device_backend", "mock"),
            )
            self.recording_interface = create_daq_interface(backend)
        except ImportError:
            self.recording_interface = None
        
        # Setup UI
        self.setup_menu()
        self.setup_widgets()
        self.setup_status()
        
        self.statusBar().addPermanentWidget(DeviceConnectedWidget(self.recording_interface))
        self.statusBar().showMessage("Ready")
    
    def setup_menu(self):
        """Setup menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
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
        self.tabs.setTabBar(WorkshopTabBar())
        self.tabs.setTabPosition(QTabWidget.TabPosition.West)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setIconSize(QSize(30, 30))
        
        # Create module widgets
        self.recording_widget = RecordingWidget(self.recording_interface)
        self.recording_widget.recording_complete.connect(self.on_recording_complete)
        
        self.model_widget = ModelWidget()
        self.model_widget.model_updated.connect(self.on_model_updated)
        
        self.characterization_widget = CharacterizationWidget(self.recording_interface)
        self.characterization_widget.characterization_complete.connect(self.on_characterization_complete)
        
        self.compensation_widget = CompensationWidget()
        self.compensation_widget.compensation_updated.connect(self.on_compensation_updated)
        
        self.rendering_widget = RenderingWidget(hardware_interface=self.recording_interface)
        self.rendering_widget.playback_started.connect(self.on_playback_started)
        self.rendering_widget.playback_stopped.connect(self.on_playback_stopped)

        self.device_status_widget = DeviceStatusWidget(self.recording_interface)
    
        # Add tabs
        icons_dir = Path(__file__).parent / "icons"
        self.tabs.addTab(self._scrollable(self.device_status_widget), QIcon(str(icons_dir / "device.svg")), "Device")
        self.tabs.addTab(self._scrollable(self.recording_widget), QIcon(str(icons_dir / "recording.svg")), "1. Recording")
        self.tabs.addTab(self._scrollable(self.model_widget), QIcon(str(icons_dir / "model.svg")), "2. Texture Model")
        self.tabs.addTab(
            self._scrollable(self.characterization_widget),
            QIcon(str(icons_dir / "characterization.svg")),
            "3. Characterization",
        )
        self.tabs.addTab(
            self._scrollable(self.compensation_widget),
            QIcon(str(icons_dir / "compensation.svg")),
            "4. Compensation",
        )
        self.tabs.addTab(
            self._scrollable(self.rendering_widget),
            QIcon(str(icons_dir / "rendering.svg")),
            "5. Rendering",
        )
        
        layout.addWidget(self.tabs)
        central_widget.setLayout(layout)

    @staticmethod
    def _scrollable(widget: QWidget) -> QScrollArea:
        """Keep complete pages accessible when the window is small."""
        viewport = QScrollArea()
        viewport.setWidgetResizable(True)
        viewport.setFrameShape(QScrollArea.Shape.NoFrame)
        viewport.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        viewport.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        viewport.setWidget(widget)
        return viewport
    
    def setup_status(self):
        """Setup status bar."""
        self.statusBar().showMessage("Ready")
    
    # Signal handlers
    
    def on_recording_complete(self, recording: Recording):
        """Handle recording completion."""
        self.current_recording = recording
        self.current_model = None
        self.model_widget.set_recording(recording)
        self.compensation_widget.set_signal(recording.data, recording.sample_rate)
        self.rendering_widget.set_recording(recording)
        
        self.statusBar().showMessage(
            f"Recording: {recording.duration:.2f}s @ {recording.sample_rate} Hz"
        )
        
        # Move to next tab
        # self.tabs.setCurrentIndex(1)
    
    def on_model_updated(self, parameters):
        """Handle model parameter update."""
        self.current_model = parameters
        self.rendering_widget.set_model(parameters)
        model_type = parameters.get("model_type", "model") if isinstance(parameters, dict) else "model"
        self.statusBar().showMessage(f"Texture model selected: {model_type}")
    
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
    
    def show_documentation(self):
        """Show a clickable documentation link and scannable QR code."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Documentation")
        dialog.setMinimumWidth(360)

        layout = QVBoxLayout(dialog)
        title = QLabel("MakeSense documentation")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        link = QLabel(f'<a href="{DOCUMENTATION_URL}">{DOCUMENTATION_URL}</a>')
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        link.setWordWrap(True)
        layout.addWidget(link)

        try:
            import qrcode

            image = qrcode.make(DOCUMENTATION_URL)
            image_bytes = BytesIO()
            image.save(image_bytes, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(image_bytes.getvalue(), "PNG")

            qr_label = QLabel()
            qr_label.setPixmap(
                pixmap.scaled(
                    220,
                    220,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            )
            qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            qr_label.setAccessibleName("QR code for the MakeSense documentation")
            layout.addWidget(qr_label)
        except ImportError:
            pass

        open_button = QPushButton("Open documentation")
        open_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DOCUMENTATION_URL))
        )
        layout.addWidget(open_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
