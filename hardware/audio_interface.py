"""
Audio Interface Abstraction
Handles audio input/output operations.
"""

from abc import ABC, abstractmethod
from typing import Optional, Callable
import numpy as np


class AudioInterface(ABC):
    """Abstract base class for audio I/O operations."""

    @abstractmethod
    def open_input(self, sample_rate: int, channels: int, buffer_size: int) -> None:
        """Open audio input stream."""
        pass

    @abstractmethod
    def close_input(self) -> None:
        """Close audio input stream."""
        pass

    @abstractmethod
    def open_output(self, sample_rate: int, channels: int, buffer_size: int) -> None:
        """Open audio output stream."""
        pass

    @abstractmethod
    def close_output(self) -> None:
        """Close audio output stream."""
        pass

    @abstractmethod
    def read_frames(self, num_frames: int) -> np.ndarray:
        """
        Read audio frames from input.
        
        Returns:
            np.ndarray: Audio data [num_frames] or [num_frames, channels]
        """
        pass

    @abstractmethod
    def write_frames(self, data: np.ndarray) -> None:
        """Write audio frames to output."""
        pass

    @abstractmethod
    def get_input_devices(self) -> list:
        """Return list of available input devices."""
        pass

    @abstractmethod
    def get_output_devices(self) -> list:
        """Return list of available output devices."""
        pass

    @abstractmethod
    def is_input_active(self) -> bool:
        """Check if input stream is active."""
        pass

    @abstractmethod
    def is_output_active(self) -> bool:
        """Check if output stream is active."""
        pass


class SoundDeviceAudioInterface(AudioInterface):
    """Audio interface implementation using sounddevice library."""

    def __init__(self):
        """Initialize with sounddevice backend."""
        try:
            import sounddevice as sd
            self.sd = sd
        except ImportError:
            raise ImportError("sounddevice library required. Install with: pip install sounddevice")
        
        self._input_stream = None
        self._output_stream = None

    def open_input(self, sample_rate: int, channels: int, buffer_size: int) -> None:
        """Open audio input stream."""
        self._input_stream = self.sd.InputStream(
            channels=channels,
            samplerate=sample_rate,
            blocksize=buffer_size,
        )
        self._input_stream.start()

    def close_input(self) -> None:
        """Close audio input stream."""
        if self._input_stream:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None

    def open_output(self, sample_rate: int, channels: int, buffer_size: int) -> None:
        """Open audio output stream."""
        self._output_stream = self.sd.OutputStream(
            channels=channels,
            samplerate=sample_rate,
            blocksize=buffer_size,
        )
        self._output_stream.start()

    def close_output(self) -> None:
        """Close audio output stream."""
        if self._output_stream:
            self._output_stream.stop()
            self._output_stream.close()
            self._output_stream = None

    def read_frames(self, num_frames: int) -> np.ndarray:
        """Read audio frames from input."""
        if not self._input_stream:
            raise RuntimeError("Input stream not open")
        return self._input_stream.read(num_frames)[0]

    def write_frames(self, data: np.ndarray) -> None:
        """Write audio frames to output."""
        if not self._output_stream:
            raise RuntimeError("Output stream not open")
        self._output_stream.write(data)

    def get_input_devices(self) -> list:
        """Return list of available input devices."""
        devices = self.sd.query_devices()
        return [d for d in devices if d['max_input_channels'] > 0]

    def get_output_devices(self) -> list:
        """Return list of available output devices."""
        devices = self.sd.query_devices()
        return [d for d in devices if d['max_output_channels'] > 0]

    def is_input_active(self) -> bool:
        """Check if input stream is active."""
        return self._input_stream is not None and self._input_stream.active

    def is_output_active(self) -> bool:
        """Check if output stream is active."""
        return self._output_stream is not None and self._output_stream.active


# Factory function
def create_audio_interface(backend: str = "sounddevice") -> AudioInterface:
    """
    Factory function to create audio interface.
    
    Args:
        backend: Audio backend name ('sounddevice', 'pyaudio', etc.)
    
    Returns:
        AudioInterface implementation
    """
    if backend == "sounddevice":
        return SoundDeviceAudioInterface()
    else:
        raise ValueError(f"Unsupported audio backend: {backend}")
