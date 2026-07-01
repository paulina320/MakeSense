"""
Characterization Module
Handles actuator transfer function characterization.
"""

import numpy as np
from typing import Optional, Dict, Tuple
from dataclasses import dataclass
from .fft_tools import compute_transfer_function


@dataclass
class ActuatorCharacterization:
    """Stores actuator transfer function and characterization data."""
    
    actuator_name: str
    frequencies: np.ndarray  # Frequency array
    magnitude: np.ndarray    # Magnitude response
    phase: np.ndarray        # Phase response
    excitation_type: str = ""
    notes: str = ""
    excitation: Optional[np.ndarray] = None
    response: Optional[np.ndarray] = None
    sample_rate: int = 44100
    
    def get_transfer_function(self, fft_size: int = 2048) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get transfer function as complex array.
        
        Returns:
            Tuple of (magnitude, phase)
        """
        return self.magnitude.copy(), self.phase.copy()


class Characterizer:
    """Characterizes actuator transfer functions."""
    
    def __init__(self, sample_rate: int = 44100):
        """Initialize characterizer."""
        self.sample_rate = sample_rate
    
    @staticmethod
    def generate_sweep(
        start_freq: float,
        end_freq: float,
        duration: float,
        sample_rate: int,
    ) -> np.ndarray:
        """
        Generate logarithmic frequency sweep (chirp).
        
        Args:
            start_freq: Start frequency in Hz
            end_freq: End frequency in Hz
            duration: Duration in seconds
            sample_rate: Sampling rate in Hz
        
        Returns:
            Sweep signal
        """
        t = np.linspace(0, duration, int(duration * sample_rate))
        
        # Logarithmic sweep
        k = (end_freq / start_freq) ** (1 / duration)
        phase = 2 * np.pi * start_freq / np.log(k) * (k ** t - 1)
        
        sweep = np.sin(phase)
        return sweep / np.max(np.abs(sweep))  # Normalize
    
    @staticmethod
    def generate_white_noise(duration: float, sample_rate: int) -> np.ndarray:
        """
        Generate white noise.
        
        Args:
            duration: Duration in seconds
            sample_rate: Sampling rate in Hz
        
        Returns:
            White noise signal
        """
        num_samples = int(duration * sample_rate)
        noise = np.random.randn(num_samples)
        return noise / np.max(np.abs(noise))
    
    @staticmethod
    def generate_impulse(
        duration: float,
        sample_rate: int,
        impulse_duration: float = 0.001,
    ) -> np.ndarray:
        """
        Generate impulse signal.
        
        Args:
            duration: Total duration in seconds
            sample_rate: Sampling rate in Hz
            impulse_duration: Duration of impulse in seconds
        
        Returns:
            Impulse signal
        """
        num_samples = int(duration * sample_rate)
        impulse_samples = int(impulse_duration * sample_rate)
        
        signal_arr = np.zeros(num_samples)
        signal_arr[0:impulse_samples] = 1.0
        
        return signal_arr
    
    def characterize(
        self,
        excitation: np.ndarray,
        response: np.ndarray,
        actuator_name: str,
        excitation_type: str = "sweep",
        fft_size: int = 2048,
    ) -> ActuatorCharacterization:
        """
        Characterize actuator from excitation and response.
        
        Args:
            excitation: Applied excitation signal
            response: Measured accelerometer response
            actuator_name: Name of actuator
            excitation_type: Type of excitation used
            fft_size: FFT size for analysis
        
        Returns:
            ActuatorCharacterization object
        """
        # Compute transfer function
        frequencies, magnitude, phase = compute_transfer_function(
            excitation,
            response,
            self.sample_rate,
            fft_size=fft_size,
        )
        
        return ActuatorCharacterization(
            actuator_name=actuator_name,
            frequencies=frequencies,
            magnitude=magnitude,
            phase=phase,
            excitation_type=excitation_type,
            excitation=excitation.copy(),
            response=response.copy(),
            sample_rate=self.sample_rate,
        )
    
    def combine_measurements(
        self,
        characterizations: list,
        weight: Optional[np.ndarray] = None,
    ) -> ActuatorCharacterization:
        """
        Combine multiple characterization measurements.
        
        Args:
            characterizations: List of ActuatorCharacterization objects
            weight: Weights for each measurement (default: equal)
        
        Returns:
            Combined ActuatorCharacterization
        """
        if not characterizations:
            raise ValueError("No characterizations provided")
        
        if weight is None:
            weight = np.ones(len(characterizations)) / len(characterizations)
        
        # Use frequencies from first measurement
        frequencies = characterizations[0].frequencies
        
        # Weighted average of magnitude and phase
        magnitude = np.zeros_like(frequencies)
        phase = np.zeros_like(frequencies)
        
        for char, w in zip(characterizations, weight):
            magnitude += w * char.magnitude
            phase += w * char.phase
        
        
        return ActuatorCharacterization(
            actuator_name=characterizations[0].actuator_name,
            frequencies=frequencies,
            magnitude=magnitude,
            phase=phase,
            notes="Combined from multiple measurements",
            sample_rate=self.sample_rate,
        )
