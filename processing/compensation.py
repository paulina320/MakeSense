"""
Compensation Module
Computes and applies compensation filters.
"""

import numpy as np
from typing import Optional, Tuple
from scipy import signal, fftpack
from dataclasses import dataclass
from .characterization import ActuatorCharacterization
from .fft_tools import inverse_filter


@dataclass
class CompensationFilter:
    """Stores compensation filter data."""
    
    frequencies: np.ndarray
    magnitude: np.ndarray
    phase: np.ndarray
    filter_coefficients: Optional[Tuple[np.ndarray, np.ndarray]] = None
    actuator_name: str = ""
    notes: str = ""


class Compensator:
    """Computes and applies compensation filters."""
    
    def __init__(self, sample_rate: int = 44100):
        """Initialize compensator."""
        self.sample_rate = sample_rate
    
    def compute_inverse_filter(
        self,
        characterization: ActuatorCharacterization,
        regularization: float = 1e-6,
        max_gain_db: float = 20.0,
        smoothing_window: int = 51,
    ) -> CompensationFilter:
        """
        Compute inverse filter from actuator characterization.
        
        Args:
            characterization: ActuatorCharacterization object
            regularization: Regularization parameter
            max_gain_db: Maximum allowed gain
            smoothing_window: Window size for smoothing
        
        Returns:
            CompensationFilter object
        """
        # Convert to complex transfer function
        H = characterization.magnitude * np.exp(1j * characterization.phase)
        
        # Compute inverse
        H_inv = inverse_filter(
            H,
            characterization.frequencies,
            regularization=regularization,
            max_gain_db=max_gain_db,
        )
        
        # Smooth for stability
        if smoothing_window > 1:
            from scipy.ndimage import uniform_filter1d
            H_inv_mag_smooth = uniform_filter1d(np.abs(H_inv), size=smoothing_window)
            H_inv = H_inv_mag_smooth * np.exp(1j * np.angle(H_inv))
        
        return CompensationFilter(
            frequencies=characterization.frequencies.copy(),
            magnitude=np.abs(H_inv),
            phase=np.angle(H_inv),
            actuator_name=characterization.actuator_name,
            notes=f"Inverse of {characterization.actuator_name}",
        )
    
    def apply_frequency_domain(
        self,
        signal_data: np.ndarray,
        compensation: CompensationFilter,
        fft_size: int = 4096,
    ) -> np.ndarray:
        """
        Apply compensation in frequency domain.
        
        Args:
            signal_data: Input signal
            compensation: CompensationFilter
            fft_size: FFT size
        
        Returns:
            Compensated signal
        """
        if signal_data.ndim > 1:
            signal_data = signal_data[:, 0]
        
        # Pad signal
        padded_length = max(len(signal_data), fft_size)
        padded_signal = np.zeros(padded_length)
        padded_signal[:len(signal_data)] = signal_data
        
        # FFT
        fft_signal = fftpack.fft(padded_signal, n=padded_length)
        
        # Interpolate compensation filter to FFT frequencies
        fft_freqs = np.fft.rfftfreq(padded_length, 1 / self.sample_rate)
        H_inv = np.interp(
            fft_freqs,
            compensation.frequencies,
            compensation.magnitude * np.exp(1j * compensation.phase),
            left=1.0,
            right=1.0,
        )
        
        # Apply compensation
        H_inv_complex = H_inv * np.exp(1j * np.interp(
            fft_freqs,
            compensation.frequencies,
            compensation.phase,
            left=0,
            right=0,
        ))
        
        # Multiply in frequency domain
        fft_signal[:len(H_inv_complex)] *= H_inv_complex
        
        # IFFT
        compensated = np.real(fftpack.ifft(fft_signal))[:len(signal_data)]
        
        return compensated
    
    def apply_time_domain(
        self,
        signal_data: np.ndarray,
        compensation: CompensationFilter,
        filter_order: int = 256,
    ) -> np.ndarray:
        """
        Apply compensation via FIR filter (time domain).
        
        Args:
            signal_data: Input signal
            compensation: CompensationFilter
            filter_order: FIR filter order
        
        Returns:
            Compensated signal
        """
        if signal_data.ndim > 1:
            signal_data = signal_data[:, 0]
        
        # Design FIR filter from magnitude and phase response
        # Inverse FFT of compensation filter response
        padded_response = np.zeros(filter_order)
        
        # Interpolate to FFT bin frequencies
        fir_freqs = np.fft.rfftfreq(filter_order, 1 / self.sample_rate)
        H_inv_mag = np.interp(
            fir_freqs,
            compensation.frequencies,
            compensation.magnitude,
            left=1.0,
            right=1.0,
        )
        H_inv_phase = np.interp(
            fir_freqs,
            compensation.frequencies,
            compensation.phase,
            left=0,
            right=0,
        )
        
        # Construct complex response and inverse FFT
        H_inv = H_inv_mag * np.exp(1j * H_inv_phase)
        
        # Pad to full FFT size
        H_full = np.zeros(filter_order, dtype=complex)
        H_full[:len(H_inv)] = H_inv
        
        # IFFT to get impulse response
        h = np.real(fftpack.ifft(H_full))
        h = h / np.sum(h)  # Normalize
        
        # Apply FIR filter
        compensated = signal.fftconvolve(signal_data, h, mode='same')
        
        return compensated
    
    def show_compensation_effect(
        self,
        original_spectrum: np.ndarray,
        compensation: CompensationFilter,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Show effect of compensation on spectrum.
        
        Args:
            original_spectrum: Original magnitude spectrum
            compensation: CompensationFilter
        
        Returns:
            Tuple of (compensated_spectrum, original_spectrum)
        """
        # Interpolate compensation to spectrum frequencies
        compensation_response = np.interp(
            np.arange(len(original_spectrum)),
            compensation.frequencies[:len(original_spectrum)],
            compensation.magnitude[:len(original_spectrum)],
            left=1.0,
            right=1.0,
        )
        
        # Apply compensation
        compensated = original_spectrum * compensation_response
        
        return compensated, original_spectrum
