"""
Device connected widget for the serial haptic backend.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel
)

from PyQt6.QtCore import QTimer

from hardware.haptic_device_interface import HapticDeviceInterface


class DeviceConnectedWidget(QWidget):
    """Compact connection status widget to add to the status bar."""

    def __init__(self, haptic_device_interface: HapticDeviceInterface):
        super().__init__()
        self.haptic_device_interface = haptic_device_interface
        self.setup_ui()
        self.update_status()

    def setup_ui(self):
        layout = QHBoxLayout()
        self.status_label = QLabel("Device: 🔴 Disconnected")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def update_status(self):
        if self.haptic_device_interface.is_connected():
            self.status_label.setText("Device: 🟢 Connected")
        else:
            self.status_label.setText("Device: 🔴 Disconnected")

    def showEvent(self, event):
        super().showEvent(event)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_status)
        self.timer.start(1000)  # Update every second


