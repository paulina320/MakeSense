"""
DAQ Interface Abstraction
Handles data acquisition from various hardware sources.
"""

from abc import ABC, abstractmethod
from typing import List, Dict
import numpy as np


class DAQInterface(ABC):
    """Abstract base class for data acquisition."""

    @abstractmethod
    def list_devices(self) -> List[Dict]:
        """Return list of available DAQ devices."""
        pass

    @abstractmethod
    def select_device(self, device_id: int) -> None:
        """Select a specific DAQ device."""
        pass

    @abstractmethod
    def configure_channels(self, channels: List[int], sample_rate: int) -> None:
        """Configure input channels and sampling rate."""
        pass

    @abstractmethod
    def start_acquisition(self) -> None:
        """Start data acquisition."""
        pass

    @abstractmethod
    def stop_acquisition(self) -> None:
        """Stop data acquisition."""
        pass

    @abstractmethod
    def read_data(self, num_samples: int) -> np.ndarray:
        """
        Read acquired data.
        
        Returns:
            np.ndarray: Data array [num_samples, num_channels]
        """
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """Check if acquisition is running."""
        pass


class MockDAQInterface(DAQInterface):
    """Mock DAQ interface for testing without hardware."""

    def __init__(self):
        """Initialize mock DAQ."""
        self._running = False
        self._connected = True
        self._rendering = False
        self._channels = [0]
        self._sample_rate = 44100
        self._sample_count = 0
        self._imu_stream_enabled = False
        self._imu_sample_rate = 100
        self._imu_sample_count = 0
        self._last_render_buffer = None

    def list_devices(self) -> List[Dict]:
        """Return mock devices."""
        return [
            {"id": 0, "name": "Mock DAQ Device 1", "channels": 8},
            {"id": 1, "name": "Mock DAQ Device 2", "channels": 4},
        ]

    def select_device(self, device_id: int) -> None:
        """Select device (mock)."""
        print(f"Selected device {device_id}")

    def configure_channels(self, channels: List[int], sample_rate: int) -> None:
        """Configure channels."""
        self._channels = channels
        self._sample_rate = sample_rate

    def start_acquisition(self) -> None:
        """Start acquisition."""
        self._running = True
        self._sample_count = 0

    def stop_acquisition(self) -> None:
        """Stop acquisition."""
        self._running = False

    def read_data(self, num_samples: int) -> np.ndarray:
        """Generate mock data."""
        if not self._running:
            raise RuntimeError("Acquisition not running")
        
        # Generate synthetic data: sine waves at different frequencies
        t = np.arange(self._sample_count, self._sample_count + num_samples) / self._sample_rate
        data = np.zeros((num_samples, len(self._channels)))
        
        for i, ch in enumerate(self._channels):
            freq = 100 + ch * 20  # Different frequency per channel
            data[:, i] = 0.5 * np.sin(2 * np.pi * freq * t)
        
        self._sample_count += num_samples
        return data

    def is_running(self) -> bool:
        """Check if running."""
        return self._running

    def connect(self, port=None) -> bool:
        """Connect to mock device."""
        self._connected = True
        return True

    def disconnect(self) -> None:
        """Disconnect mock device."""
        self._connected = False
        self._running = False
        self._rendering = False

    def is_connected(self) -> bool:
        """Check mock connection status."""
        return self._connected

    def get_available_ports(self) -> list:
        """Return mock serial-like ports."""
        return ["MOCK"]

    def get_status(self) -> dict:
        """Return mock status payload."""
        return {
            "connected": self._connected,
            "port": "MOCK",
            "firmware": "mock",
            "pixi_ok": True,
            "imu_ok": True,
            "imu_stream": self._imu_stream_enabled,
            "imu_rate": self._imu_sample_rate,
            "acquiring": self._running,
            "rendering": self._rendering,
            "sample_rate": self._sample_rate,
            "dropped_frames": 0,
            "underruns": 0,
        }

    def configure_channel(self, pin: int, role: str, **kwargs) -> str:
        """Accept channel configuration in mock mode."""
        return f"OK mock channel {pin} {role}"

    def configure_imu_stream(
        self, sample_rate: int = 100, enabled: bool = True, imu_fields=None
    ) -> str:
        """Configure mock IMU streaming."""
        self._imu_sample_rate = int(sample_rate)
        self._imu_stream_enabled = bool(enabled)
        return "OK mock imu stream"

    def read_available_imu(self, max_samples: int = 16) -> list:
        """Generate mock IMU samples while acquisition and IMU streaming are active."""
        if not self._running or not self._imu_stream_enabled:
            return []
        count = max(1, min(max_samples, self._imu_sample_rate // 20))
        samples = []
        for _ in range(count):
            t = self._imu_sample_count / self._imu_sample_rate
            timestamp_us = int(t * 1_000_000)
            samples.append({
                "timestamp_us": timestamp_us,
                "ok": True,
                "accel_ok": True,
                "gyro_ok": True,
                "mag_ok": True,
                "bmp_ok": True,
                "accel": [
                    0.10 * np.sin(2 * np.pi * 2 * t),
                    0.05 * np.sin(2 * np.pi * 3 * t),
                    1.0 + 0.10 * np.sin(2 * np.pi * 4 * t),
                ],
                "accel_unit": "g",
                "gyro": [
                    int(128 * np.sin(2 * np.pi * 5 * t)),
                    int(128 * np.sin(2 * np.pi * 6 * t)),
                    int(128 * np.sin(2 * np.pi * 7 * t)),
                ],
                "mag": [
                    int(64 * np.sin(2 * np.pi * 1 * t)),
                    int(64 * np.cos(2 * np.pi * 1 * t)),
                    int(64 * np.sin(2 * np.pi * 0.5 * t)),
                ],
                "bmp_pressure_raw": int(100000 + 100 * np.sin(2 * np.pi * 0.2 * t)),
                "bmp_temperature_raw": int(2500 + 10 * np.sin(2 * np.pi * 0.1 * t)),
            })
            self._imu_sample_count += 1
        return samples

    def start_rendering(self) -> None:
        """Start mock rendering."""
        self._rendering = True

    def stop_rendering(self) -> None:
        """Stop mock rendering."""
        self._rendering = False

    def write_render_buffer(self, signal: np.ndarray) -> None:
        """Store the latest mock render buffer."""
        self._last_render_buffer = np.asarray(signal)

    def configure_render_outputs(self, channels: list[int]) -> None:
        """Accept render output configuration in mock mode."""
        self._render_channels = channels or [1]

    def configure_render_timing(self, sample_rate: int) -> None:
        """Set mock render sample rate."""
        self._sample_rate = int(sample_rate)

    def recent_errors(self) -> list:
        """Return recent mock protocol errors."""
        return []
    
    def record_response(self, excitation: np.ndarray, *args, **kwargs) -> np.ndarray:
        """Simulate recording response to excitation."""
        # For testing, just return a delayed and attenuated version of the excitation
        delay_samples = int(0.01 * self._sample_rate)  # 10 ms delay
        attenuation = 0.5
        response = np.zeros_like(excitation)
        if len(excitation) > delay_samples:
            response[delay_samples:] = attenuation * excitation[:-delay_samples]
        return response


# Factory function
def create_daq_interface(backend: str = "mock") -> DAQInterface:
    """
    Factory function to create DAQ interface.
    
    Args:
        backend: DAQ backend ('mock', 'nidaqmx', etc.)
    
    Returns:
        DAQInterface implementation
    """
    if backend == "mock":
        return MockDAQInterface()
    elif backend in ("haptic_device", "serial"):
        from .haptic_device_interface import create_haptic_device_interface
        try:
            from config import config
            settings = config.HAPTIC_DEVICE_CONFIG
        except Exception:
            settings = {}
        return create_haptic_device_interface(settings)
    else:
        raise ValueError(f"Unsupported DAQ backend: {backend}")
