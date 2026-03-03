"""
Recording Module
Handles audio recording and data acquisition.
"""

import numpy as np
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RecordingMetadata:
    """Metadata for a recording."""
    
    surface_type: str = ""
    velocity: Optional[float] = None
    device_used: str = ""
    notes: str = ""
    timestamp: datetime = None
    duration: float = 0.0
    sample_rate: int = 44100
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class Recording:
    """Represents a single recording."""
    
    def __init__(
        self,
        data: np.ndarray,
        sample_rate: int,
        metadata: Optional[RecordingMetadata] = None,
    ):
        """
        Initialize recording.
        
        Args:
            data: Audio data [samples] or [samples, channels]
            sample_rate: Sampling rate in Hz
            metadata: Recording metadata
        """
        self.data = data
        self.sample_rate = sample_rate
        self.metadata = metadata or RecordingMetadata()
        self.metadata.sample_rate = sample_rate
        self.metadata.duration = len(data) / sample_rate
    
    @property
    def duration(self) -> float:
        """Get recording duration in seconds."""
        return len(self.data) / self.sample_rate
    
    @property
    def num_channels(self) -> int:
        """Get number of channels."""
        if self.data.ndim == 1:
            return 1
        return self.data.shape[1]
    
    def get_channel(self, channel: int) -> np.ndarray:
        """Extract single channel."""
        if self.data.ndim == 1:
            if channel == 0:
                return self.data
            else:
                raise IndexError(f"Recording has only 1 channel")
        return self.data[:, channel]
    
    def trim(self, start_time: float, end_time: float) -> "Recording":
        """
        Trim recording to time range.
        
        Args:
            start_time: Start time in seconds
            end_time: End time in seconds
        
        Returns:
            New trimmed Recording
        """
        start_sample = int(start_time * self.sample_rate)
        end_sample = int(end_time * self.sample_rate)
        
        trimmed_data = self.data[start_sample:end_sample]
        return Recording(trimmed_data, self.sample_rate, self.metadata)
    
    def resample(self, new_sample_rate: int) -> "Recording":
        """
        Resample recording to new sample rate.
        
        Args:
            new_sample_rate: New sampling rate in Hz
        
        Returns:
            New resampled Recording
        """
        from scipy import signal
        
        if new_sample_rate == self.sample_rate:
            return self
        
        # Calculate resampling factor
        ratio = new_sample_rate / self.sample_rate
        new_length = int(len(self.data) * ratio)
        
        # Resample each channel
        if self.data.ndim == 1:
            resampled = signal.resample(self.data, new_length)
        else:
            resampled = signal.resample(self.data, new_length, axis=0)
        
        return Recording(resampled, new_sample_rate, self.metadata)
    
    def apply_gain(self, gain_db: float) -> "Recording":
        """
        Apply gain to recording.
        
        Args:
            gain_db: Gain in decibels
        
        Returns:
            New Recording with gain applied
        """
        gain_linear = 10 ** (gain_db / 20)
        processed = self.data * gain_linear
        return Recording(processed, self.sample_rate, self.metadata)
    
    def normalize(self, target_db: float = -3.0) -> "Recording":
        """
        Normalize recording to target RMS level.
        
        Args:
            target_db: Target RMS level in dB
        
        Returns:
            Normalized Recording
        """
        rms = np.sqrt(np.mean(self.data ** 2))
        target_rms = 10 ** (target_db / 20)
        
        if rms > 0:
            gain = target_rms / rms
            processed = self.data * gain
        else:
            processed = self.data
        
        return Recording(processed, self.sample_rate, self.metadata)


class RecordingBuffer:
    """Circular buffer for recording acquisition."""
    
    def __init__(self, capacity: int, num_channels: int = 1):
        """
        Initialize recording buffer.
        
        Args:
            capacity: Buffer capacity in samples
            num_channels: Number of channels
        """
        self.capacity = capacity
        self.num_channels = num_channels
        self.buffer = np.zeros((capacity, num_channels))
        self.write_pos = 0
        self.is_full = False
    
    def write(self, data: np.ndarray) -> None:
        """Write data to buffer."""
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        
        num_samples = len(data)
        remaining = self.capacity - self.write_pos
        
        if num_samples <= remaining:
            self.buffer[self.write_pos:self.write_pos + num_samples] = data
            self.write_pos += num_samples
        else:
            # Wrap around
            self.buffer[self.write_pos:] = data[:remaining]
            overflow = num_samples - remaining
            self.buffer[:overflow] = data[remaining:]
            self.write_pos = overflow
            self.is_full = True
    
    def get_data(self) -> np.ndarray:
        """Get accumulated data."""
        if self.is_full:
            return np.vstack([
                self.buffer[self.write_pos:],
                self.buffer[:self.write_pos]
            ])
        else:
            return self.buffer[:self.write_pos]
    
    def clear(self) -> None:
        """Clear buffer."""
        self.buffer.fill(0)
        self.write_pos = 0
        self.is_full = False
