"""
Hardware package initialization.
Provides factories for hardware interfaces.
"""

from .audio_interface import create_audio_interface, AudioInterface
from .daq_interface import create_daq_interface, DAQInterface
from .accelerometer_interface import create_accelerometer_interface, AccelerometerInterface
from .haptic_device_interface import (
    HapticDeviceInterface,
    create_haptic_device_interface,
)

__all__ = [
    "create_audio_interface",
    "create_daq_interface",
    "create_haptic_device_interface",
    "create_accelerometer_interface",
    "AudioInterface",
    "DAQInterface",
    "AccelerometerInterface",
    "HapticDeviceInterface",
]
