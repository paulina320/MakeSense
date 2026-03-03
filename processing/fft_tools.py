"""
FFT Tools Module
Provides frequency domain analysis utilities.
"""

import numpy as np
from scipy import signal, fftpack
from typing import Tuple, Optional


def compute_fft(
    data: np.ndarray,
    sample_rate: int,
    window: str = "hann",
    fft_size: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute FFT of signal.
    
    Args:
        data: Input signal [samples] or [samples, channels]
        sample_rate: Sampling rate in Hz
        window: Window function name
        fft_size: FFT size (if None, uses signal length)
    
    Returns:
        Tuple of (frequencies, magnitudes in dB)
    """
    if data.ndim > 1:
        data = data[:, 0]  # Use first channel
    
    if fft_size is None:
        fft_size = len(data)
    
    # Apply window
    window_func = signal.get_window(window, len(data))
    windowed_data = data * window_func
    
    # Compute FFT
    fft_vals = fftpack.fft(windowed_data, n=fft_size)
    magnitudes = np.abs(fft_vals[:fft_size // 2])
    
    # Convert to dB
    magnitudes_db = 20 * np.log10(magnitudes + 1e-10)
    
    # Frequencies
    frequencies = np.fft.rfftfreq(fft_size, 1 / sample_rate)
    
    return frequencies[:fft_size // 2], magnitudes_db


def compute_spectrogram(
    data: np.ndarray,
    sample_rate: int,
    window_size: int = 512,
    overlap: float = 0.75,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute spectrogram.
    
    Args:
        data: Input signal [samples] or [samples, channels]
        sample_rate: Sampling rate in Hz
        window_size: STFT window size
        overlap: Overlap ratio (0-1)
    
    Returns:
        Tuple of (frequencies, times, spectrogram magnitudes in dB)
    """
    if data.ndim > 1:
        data = data[:, 0]
    
    overlap_samples = int(window_size * overlap)
    noverlap = window_size - overlap_samples
    
    frequencies, times, Sxx = signal.spectrogram(
        data,
        fs=sample_rate,
        nperseg=window_size,
        noverlap=noverlap,
        window='hann',
    )
    
    Sxx_db = 20 * np.log10(np.abs(Sxx) + 1e-10)
    
    return frequencies, times, Sxx_db


def compute_transfer_function(
    excitation: np.ndarray,
    response: np.ndarray,
    sample_rate: int,
    fft_size: int = 2048,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute transfer function H(f) = Response(f) / Excitation(f).
    
    Args:
        excitation: Excitation signal
        response: System response signal
        sample_rate: Sampling rate
        fft_size: FFT size
    
    Returns:
        Tuple of (frequencies, magnitude response, phase response)
    """
    if excitation.ndim > 1:
        excitation = excitation[:, 0]
    if response.ndim > 1:
        response = response[:, 0]
    
    # Pad to same length
    max_len = max(len(excitation), len(response))
    exc_padded = np.pad(excitation, (0, max_len - len(excitation)))
    resp_padded = np.pad(response, (0, max_len - len(response)))
    
    # Apply window
    window = signal.get_window('hann', max_len)
    exc_windowed = exc_padded * window
    resp_windowed = resp_padded * window
    
    # Compute FFT
    fft_exc = fftpack.fft(exc_windowed, n=fft_size)
    fft_resp = fftpack.fft(resp_windowed, n=fft_size)
    
    # Transfer function (avoid division by zero)
    H = fft_resp / (fft_exc + 1e-10)
    
    # Extract magnitude and phase
    magnitude = np.abs(H[:fft_size // 2])
    phase = np.angle(H[:fft_size // 2])
    
    # Frequencies
    frequencies = np.fft.rfftfreq(fft_size, 1 / sample_rate)
    
    return frequencies[:fft_size // 2], magnitude, phase



def smooth_signal(
    data: np.ndarray,
    window_length: int = 51,
    polyorder: int = 3,
) -> np.ndarray:
    """
    Apply Savitzky-Golay smoothing filter.
    
    Args:
        data: Input signal
        window_length: Window length (must be odd)
        polyorder: Polynomial order
    
    Returns:
        Smoothed signal
    """
    if window_length % 2 == 0:
        window_length += 1
    
    return signal.savgol_filter(data, window_length, polyorder)


def inverse_filter(
    H: np.ndarray,
    frequencies: np.ndarray,
    regularization: float = 1e-6,
    max_gain_db: float = 20.0,
) -> np.ndarray:
    """
    Compute inverse filter with regularization.
    
    Args:
        H: Transfer function (complex)
        frequencies: Frequency array
        regularization: Regularization parameter for stability
        max_gain_db: Maximum allowed gain in dB
    
    Returns:
        Inverse filter H_inv
    """
    # Avoid division by very small values
    H_mag = np.abs(H) + regularization
    H_phase = np.angle(H)
    
    # Inverse magnitude response
    H_inv_mag = 1.0 / H_mag
    
    # Limit maximum gain
    max_gain_linear = 10 ** (max_gain_db / 20)
    H_inv_mag = np.clip(H_inv_mag, 0, max_gain_linear)
    
    # Reconstruct complex inverse filter
    H_inv = H_inv_mag * np.exp(-1j * H_phase)
    
    return H_inv
