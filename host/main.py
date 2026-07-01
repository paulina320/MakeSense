"""
Haptic Software Application
Main entry point for the PyQt6 GUI application.

Features:
- Recording: Capture haptic texture signals
- Texture Modeling: Represent textures with various models
- Characterization: Characterize actuator transfer functions
- Compensation: Design and apply compensation filters
- Rendering: Synthesize and playback haptic textures
- Evaluation: Conduct subjective user studies

Architecture:
- UI Layer: PyQt6 widgets
- Processing Layer: Pure Python signal processing
- Hardware Layer: DAQ and haptic-device abstraction
- Data Layer: File I/O
- Visualization: Real-time plotting support
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from ui.main_window import MainWindow
from ui.theme import MAKESENSE_THEME


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    
    try:
        app.setStyle('Fusion')
    except:
        pass
    app.setStyleSheet(MAKESENSE_THEME)
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "ui" / "icons" / "makesense.svg")))
    
    window = MainWindow()
    available = app.primaryScreen().availableGeometry()
    window.resize(
        min(window.width(), max(1, available.width() - 40)),
        min(window.height(), max(1, available.height() - 40)),
    )
    window.move(available.center() - window.rect().center())
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
