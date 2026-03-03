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
        self._channels = [0]
        self._sample_rate = 44100
        self._sample_count = 0

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
    
    def record_response(self, excitation: np.ndarray) -> np.ndarray:
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
    else:
        raise ValueError(f"Unsupported DAQ backend: {backend}")
