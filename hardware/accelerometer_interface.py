"""
Accelerometer Interface Abstraction
Handles communication with accelerometer sensors.
"""

from abc import ABC, abstractmethod
from typing import Optional
import numpy as np


class AccelerometerInterface(ABC):
    """Abstract base class for accelerometer communication."""

    @abstractmethod
    def connect(self, port: Optional[str] = None) -> bool:
        """
        Connect to accelerometer device.
        
        Args:
            port: Serial port (e.g., '/dev/ttyUSB0', 'COM3')
        
        Returns:
            bool: Connection success
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from device."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check connection status."""
        pass

    @abstractmethod
    def configure_sample_rate(self, sample_rate: int) -> None:
        """Configure sampling rate."""
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
    def read_samples(self, num_samples: int) -> np.ndarray:
        """
        Read accelerometer samples.
        
        Returns:
            np.ndarray: 3-axis acceleration data [num_samples, 3] in m/s²
        """
        pass

    @abstractmethod
    def get_available_ports(self) -> list:
        """Return list of available serial ports."""
        pass


class MockAccelerometerInterface(AccelerometerInterface):
    """Mock accelerometer interface for testing."""

    def __init__(self):
        """Initialize mock accelerometer."""
        self._connected = False
        self._acquiring = False
        self._sample_rate = 44100
        self._sample_count = 0

    def connect(self, port: Optional[str] = None) -> bool:
        """Connect (mock)."""
        self._connected = True
        return True

    def disconnect(self) -> None:
        """Disconnect (mock)."""
        self._connected = False
        self._acquiring = False

    def is_connected(self) -> bool:
        """Check connection."""
        return self._connected

    def configure_sample_rate(self, sample_rate: int) -> None:
        """Configure sample rate."""
        self._sample_rate = sample_rate

    def start_acquisition(self) -> None:
        """Start acquisition."""
        if not self._connected:
            raise RuntimeError("Not connected")
        self._acquiring = True
        self._sample_count = 0

    def stop_acquisition(self) -> None:
        """Stop acquisition."""
        self._acquiring = False

    def read_samples(self, num_samples: int) -> np.ndarray:
        """Generate mock accelerometer data."""
        if not self._acquiring:
            raise RuntimeError("Acquisition not running")
        
        # Generate synthetic 3-axis data (X, Y, Z)
        t = np.arange(self._sample_count, self._sample_count + num_samples) / self._sample_rate
        data = np.zeros((num_samples, 3))
        
        # X: 100 Hz sine wave
        data[:, 0] = 9.81 * 0.3 * np.sin(2 * np.pi * 100 * t)
        # Y: 150 Hz sine wave
        data[:, 1] = 9.81 * 0.2 * np.sin(2 * np.pi * 150 * t)
        # Z: Gravity + 50 Hz vibration
        data[:, 2] = 9.81 + 9.81 * 0.1 * np.sin(2 * np.pi * 50 * t)
        
        self._sample_count += num_samples
        return data

    def get_available_ports(self) -> list:
        """Return mock available ports."""
        return ["/dev/ttyUSB0", "/dev/ttyUSB1", "COM3", "COM4"]


class ADX358AccelerometerInterface(AccelerometerInterface):
    """Interface for ADX358 Accelerometer via serial connection."""

    def __init__(self):
        """Initialize ADX358 interface."""
        self._connected = False
        self._acquiring = False
        self._sample_rate = 44100
        self._port = None
        self._serial_connection = None

    def connect(self, port: Optional[str] = None) -> bool:
        """Connect to ADX358 device."""
        try:
            import serial
            if port is None:
                port = self.get_available_ports()[0]
            
            self._serial_connection = serial.Serial(port, baudrate=115200, timeout=1.0)
            self._port = port
            self._connected = True
            return True
        except Exception as e:
            print(f"Failed to connect to accelerometer: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from device."""
        if self._serial_connection:
            self.stop_acquisition()
            self._serial_connection.close()
            self._serial_connection = None
        self._connected = False

    def is_connected(self) -> bool:
        """Check connection status."""
        return self._connected and self._serial_connection is not None

    def configure_sample_rate(self, sample_rate: int) -> None:
        """Configure sampling rate."""
        self._sample_rate = sample_rate
        # Send configuration command to device
        if self._connected:
            config_cmd = f"SET_SAMPLE_RATE {sample_rate}\n"
            self._serial_connection.write(config_cmd.encode())

    def start_acquisition(self) -> None:
        """Start data acquisition."""
        if not self._connected:
            raise RuntimeError("Not connected")
        self._acquiring = True
        if self._serial_connection:
            self._serial_connection.write(b"START_ACQU\n")

    def stop_acquisition(self) -> None:
        """Stop data acquisition."""
        self._acquiring = False
        if self._serial_connection:
            self._serial_connection.write(b"STOP_ACQU\n")

    def read_samples(self, num_samples: int) -> np.ndarray:
        """Read accelerometer samples from device."""
        if not self._acquiring:
            raise RuntimeError("Acquisition not running")
        
        if not self._serial_connection:
            raise RuntimeError("Serial connection lost")
        
        data = np.zeros((num_samples, 3))
        
        for i in range(num_samples):
            line = self._serial_connection.readline().decode().strip()
            if line:
                try:
                    # Expected format: "X,Y,Z"
                    values = [float(x) for x in line.split(',')]
                    data[i, :] = values[:3]
                except ValueError:
                    pass
        
        return data

    def get_available_ports(self) -> list:
        """Return available serial ports."""
        try:
            import serial.tools.list_ports
            ports = [port.device for port in serial.tools.list_ports.comports()]
            return ports if ports else ["/dev/ttyUSB0"]
        except Exception:
            return ["/dev/ttyUSB0", "COM3"]


# Factory function
def create_accelerometer_interface(backend: str = "mock") -> AccelerometerInterface:
    """
    Factory function to create accelerometer interface.
    
    Args:
        backend: Accelerometer backend ('mock', 'adx358', etc.)
    
    Returns:
        AccelerometerInterface implementation
    """
    if backend == "mock":
        return MockAccelerometerInterface()
    elif backend == "adx358":
        return ADX358AccelerometerInterface()
    else:
        raise ValueError(f"Unsupported accelerometer backend: {backend}")
