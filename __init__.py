"""
Haptic Software Package
A comprehensive PyQt6 application for haptic texture recording, modeling,
characterization, compensation, rendering, and evaluation.
"""

__version__ = "1.0.0"
__author__ = "Haptic Software Team"
__description__ = "Haptic Texture Recording and Rendering Software"

# Import main components
from ui.main_window import MainWindow
from processing import (
    Recording,
    create_texture_model,
    Characterizer,
    Compensator,
    Renderer,
)
from hardware import (
    create_audio_interface,
    create_daq_interface,
    create_accelerometer_interface,
)
from data import ProjectManager, FileIO

__all__ = [
    "MainWindow",
    "Recording",
    "create_texture_model",
    "Characterizer",
    "Compensator",
    "Renderer",
    "create_audio_interface",
    "create_daq_interface",
    "create_accelerometer_interface",
    "ProjectManager",
    "FileIO",
]
