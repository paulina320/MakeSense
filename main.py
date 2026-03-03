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
- Hardware Layer: Device abstraction (audio, DAQ, accelerometer)
- Data Layer: Project management and file I/O
- Visualization: Real-time plotting support
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow


def main():
    """Main entry point."""
    # Create application
    app = QApplication(sys.argv)
    
    # Set application style
    try:
        app.setStyle('Fusion')  # Modern cross-platform style
    except:
        pass
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
