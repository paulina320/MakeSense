"""
Texture representation models for tactile signal synthesis.

The models follow the texture-processing flow used in the referenced tactile
texture work: operate on the friction/response signal in the tactile band,
encode a compact spectral or time-series representation, and synthesize with
random phase/noise where phase is not the perceptually important quantity.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

import numpy as np
from scipy import signal
from scipy.fftpack import dct, idct
from scipy.linalg import solve_toeplitz
from scipy.optimize import minimize
from scipy.stats import beta as beta_dist


TACTILE_LOW_HZ = 20.0
TACTILE_HIGH_HZ = 1000.0


class TextureModel(ABC):
    """Abstract base class for texture models."""

    def __init__(self, name: str, description: str, preprocessing_mode: str = "whole_signal", setup_response: Dict[str, Any] | None = None):
        self.name = name
        self.description = description
        self.parameters: Dict[str, Any] = {}
        self.preprocessing_mode = preprocessing_mode
        self.setup_response = setup_response

    @abstractmethod
    def encode(self, recording_data: np.ndarray, sample_rate: int) -> Dict[str, Any]:
        """Encode recording into model parameters."""

    @abstractmethod
    def decode(self, parameters: Dict[str, Any], duration: float, sample_rate: int) -> np.ndarray:
        """Decode model parameters back to a signal."""

    @abstractmethod
    def get_parameter_info(self) -> Dict[str, Dict]:
        """Get information about model parameters."""


def _mono(data: np.ndarray) -> np.ndarray:
    data = np.asarray(data, dtype=np.float64)
    if data.ndim > 1:
        data = data[:, 0]
    data = np.nan_to_num(data)
    return data - np.mean(data)


def _safe_high(sample_rate: int, high_hz: float = TACTILE_HIGH_HZ) -> float:
    return min(float(high_hz), 0.45 * float(sample_rate))


def _bandpass(data: np.ndarray, sample_rate: int, low_hz: float = TACTILE_LOW_HZ, high_hz: float = TACTILE_HIGH_HZ) -> np.ndarray:
    high = _safe_high(sample_rate, high_hz)
    if high <= low_hz:
        return data
    sos = signal.butter(4, [low_hz, high], btype="bandpass", fs=sample_rate, output="sos")
    if len(data) < 32:
        return signal.sosfilt(sos, data)
    return signal.sosfiltfilt(sos, data)


def _preprocess(
    data: np.ndarray,
    sample_rate: int,
    preprocessing_mode: str = "whole_signal",
    setup_response: Dict[str, Any] | None = None,
) -> np.ndarray:
    mono = _mono(data)
    if preprocessing_mode == "no_preprocessing":
        return mono
    if preprocessing_mode == "hanning_sweep_average":
        mono = _hanning_sweep_average(mono)
    if setup_response:
        mono = _compensate_time_signal(mono, sample_rate, setup_response)
    processed = _bandpass(mono, sample_rate)
    peak = np.max(np.abs(processed))
    return processed / peak if peak > 1e-12 else processed


def _hanning_sweep_average(data: np.ndarray, segment_samples: int = 4000) -> np.ndarray:
    """Extract thresholded sweep segments and average Hanning-windowed segments."""
    if len(data) < segment_samples:
        padded = np.zeros(segment_samples)
        padded[: len(data)] = data
        return padded * np.hanning(segment_samples)

    abs_signal = np.abs(data)
    threshold = float(np.mean(abs_signal))
    active = abs_signal > threshold
    segments = []
    index = 0
    while index < len(active):
        if not active[index]:
            index += 1
            continue
        start = index
        while index < len(active) and active[index]:
            index += 1
        end = index
        midpoint = (start + end) // 2
        left = midpoint - segment_samples // 2
        right = left + segment_samples
        if left < 0 or right > len(data):
            continue
        segments.append(data[left:right] * np.hanning(segment_samples))

    if not segments:
        center = len(data) // 2
        left = max(0, min(len(data) - segment_samples, center - segment_samples // 2))
        return data[left:left + segment_samples] * np.hanning(segment_samples)
    return np.mean(np.asarray(segments), axis=0)


def _compensate_time_signal(data: np.ndarray, sample_rate: int, setup_response: Dict[str, Any]) -> np.ndarray:
    freqs = np.fft.rfftfreq(len(data), 1.0 / sample_rate)
    spectrum = np.fft.rfft(data)
    response_mag = _interpolated_response_magnitude(freqs, setup_response)
    return np.fft.irfft(spectrum / np.maximum(response_mag, 1e-6), n=len(data))


def _interpolated_response_magnitude(freqs: np.ndarray, setup_response: Dict[str, Any]) -> np.ndarray:
    response_freqs = np.asarray(setup_response.get("frequencies", []), dtype=np.float64)
    if len(response_freqs) == 0:
        return np.ones_like(freqs)
    if "response" in setup_response:
        response = np.asarray(setup_response["response"])
        magnitude = np.abs(response)
    elif "magnitude" in setup_response:
        magnitude = np.asarray(setup_response["magnitude"], dtype=np.float64)
    else:
        return np.ones_like(freqs)
    magnitude = np.nan_to_num(magnitude, nan=1.0, posinf=1.0, neginf=1.0)
    return np.interp(freqs, response_freqs, np.maximum(magnitude, 1e-6), left=magnitude[0], right=magnitude[-1])


def _rms_match(signal_data: np.ndarray, reference_rms: float) -> np.ndarray:
    signal_data = np.nan_to_num(np.asarray(signal_data, dtype=np.float64))
    rms = np.sqrt(np.mean(signal_data**2)) if len(signal_data) else 0.0
    if rms > 1e-12:
        signal_data = signal_data * (reference_rms / rms)
    peak = np.max(np.abs(signal_data)) if len(signal_data) else 0.0
    return (signal_data / peak).astype(np.float32) if peak > 1.0 else signal_data.astype(np.float32)


def _spectrum(data: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    window = np.hanning(len(data))
    spec = np.fft.rfft(data * window)
    freqs = np.fft.rfftfreq(len(data), 1.0 / sample_rate)
    mag = np.abs(spec) / max(1, len(data))
    return freqs, mag


def _select_separated_peaks(freqs: np.ndarray, mag: np.ndarray, count: int, low_hz: float, high_hz: float, ratio: float = 1.12):
    mask = (freqs >= low_hz) & (freqs <= high_hz) & np.isfinite(mag)
    candidates = np.where(mask)[0]
    order = candidates[np.argsort(mag[candidates])[::-1]]
    selected = []
    for index in order:
        freq = freqs[index]
        if freq <= 0:
            continue
        if all(max(freq, freqs[other]) / max(1e-9, min(freq, freqs[other])) >= ratio for other in selected):
            selected.append(index)
            if len(selected) >= count:
                break
    if not selected and len(candidates):
        selected.append(int(candidates[np.argmax(mag[candidates])]))
    return np.asarray(selected, dtype=int)


class RawSignalModel(TextureModel):
    """Raw signal, only normalized to a single channel."""

    def __init__(self, preprocessing_mode: str = "whole_signal", setup_response: Dict[str, Any] | None = None):
        super().__init__("Raw Signal", "Unprocessed recording", preprocessing_mode, setup_response)

    def encode(self, recording_data: np.ndarray, sample_rate: int) -> Dict[str, Any]:
        return {"signal": _preprocess(recording_data, sample_rate, self.preprocessing_mode, self.setup_response).astype(np.float32), "sample_rate": sample_rate}

    def decode(self, parameters: Dict[str, Any], duration: float, sample_rate: int) -> np.ndarray:
        return np.asarray(parameters.get("signal", np.array([])), dtype=np.float32)

    def get_parameter_info(self) -> Dict[str, Dict]:
        return {"signal": {"type": "array", "description": "Raw signal"}}


class AutoRegressionModel(TextureModel):
    """All-pole autoregressive model."""

    def __init__(self, order: int = 6, preprocessing_mode: str = "whole_signal", setup_response: Dict[str, Any] | None = None):
        super().__init__("AR", "All-pole autoregressive texture model", preprocessing_mode, setup_response)
        self.order = max(1, int(order))

    def encode(self, recording_data: np.ndarray, sample_rate: int) -> Dict[str, Any]:
        data = _preprocess(recording_data, sample_rate, self.preprocessing_mode, self.setup_response)
        order = min(self.order, max(1, len(data) // 4))
        corr = np.correlate(data, data, mode="full")[len(data) - 1 : len(data) + order]
        corr = corr / max(1, len(data))
        corr[0] = max(corr[0], 1e-9)
        try:
            ar_coeff = solve_toeplitz((corr[:order], corr[:order]), corr[1 : order + 1])
        except Exception:
            ar_coeff = np.zeros(order)
        return {
            "ar_coeff": np.asarray(ar_coeff, dtype=np.float64),
            "order": order,
            "rms": float(np.sqrt(np.mean(data**2))),
            "sample_rate": sample_rate,
        }

    def decode(self, parameters: Dict[str, Any], duration: float, sample_rate: int) -> np.ndarray:
        coeff = np.asarray(parameters.get("ar_coeff", []), dtype=np.float64)
        num_samples = max(1, int(duration * sample_rate))
        excitation = np.random.randn(num_samples)
        reconstructed = signal.lfilter([1.0], np.concatenate([[1.0], -coeff]), excitation)
        reconstructed = _bandpass(reconstructed, sample_rate)
        return _rms_match(reconstructed, parameters.get("rms", 0.2))

    def get_parameter_info(self) -> Dict[str, Dict]:
        return {"ar_coeff": {"type": "array", "description": "All-pole AR coefficients"}}


class MFCCModel(TextureModel):
    """Mel-frequency cepstral coefficient model using band-power reconstruction."""

    def __init__(
        self,
        num_coefficients: int = 10,
        num_filters: int = 26,
        frame_size: float = 0.025,
        frame_stride: float = 0.010,
        preprocessing_mode: str = "whole_signal",
        setup_response: Dict[str, Any] | None = None,
    ):
        super().__init__("MFCC", "Mel filterbank power representation", preprocessing_mode, setup_response)
        self.num_coefficients = int(num_coefficients)
        self.num_filters = int(num_filters)
        self.frame_size = float(frame_size)
        self.frame_stride = float(frame_stride)

    def encode(self, recording_data: np.ndarray, sample_rate: int) -> Dict[str, Any]:
        data = _preprocess(recording_data, sample_rate, self.preprocessing_mode, self.setup_response)
        nfft = 1024
        windowed = np.zeros(nfft)
        copy_len = min(len(data), nfft)
        windowed[:copy_len] = data[:copy_len] * np.hanning(copy_len)
        power = (np.abs(np.fft.rfft(windowed, n=nfft)) / max(1, copy_len)) ** 2
        mel_filters = _mel_filterbank(self.num_filters, nfft, sample_rate, TACTILE_LOW_HZ, _safe_high(sample_rate))
        energies = np.maximum(mel_filters @ power, 1e-12)
        coeffs = dct(np.log(energies), type=2, norm="ortho")[: self.num_coefficients]
        band_frequencies = _mel_band_centers(self.num_filters, nfft, sample_rate, TACTILE_LOW_HZ, _safe_high(sample_rate))
        band_edges = _mel_band_edges(self.num_filters, sample_rate, TACTILE_LOW_HZ, _safe_high(sample_rate))
        return {
            "coeffs": coeffs,
            "band_energies": energies,
            "band_frequencies": band_frequencies,
            "band_edges": band_edges,
            "num_filters": self.num_filters,
            "nfft": nfft,
            "rms": float(np.sqrt(np.mean(data**2))),
            "sample_rate": sample_rate,
        }

    def decode(self, parameters: Dict[str, Any], duration: float, sample_rate: int) -> np.ndarray:
        num_samples = max(1, int(duration * sample_rate))
        analysis_nfft = int(parameters.get("nfft", 1024))
        synth_nfft = int(2 ** np.ceil(np.log2(max(num_samples, analysis_nfft))))
        num_filters = int(parameters.get("num_filters", self.num_filters))
        coeffs = np.asarray(parameters.get("coeffs", np.zeros(self.num_coefficients)), dtype=np.float64)
        log_energies = idct(coeffs, type=2, n=num_filters, norm="ortho")
        mel_filters = _mel_filterbank(num_filters, analysis_nfft, sample_rate, TACTILE_LOW_HZ, _safe_high(sample_rate))
        mag = np.sqrt(np.maximum(np.exp(log_energies) @ np.linalg.pinv(mel_filters.T), 0.0))
        return _random_phase_synthesis(mag, synth_nfft, num_samples, sample_rate, parameters.get("rms", 0.2))

    def get_parameter_info(self) -> Dict[str, Dict]:
        return {"coeffs": {"type": "array", "description": "MFCC coefficients"}}


class SpectralPeakModel(TextureModel):
    """Spectral-peak representation with approximately JND-separated peaks."""

    def __init__(self, num_peaks: int = 10, preprocessing_mode: str = "whole_signal", setup_response: Dict[str, Any] | None = None):
        super().__init__("sPeak", "Separated spectral peak texture model", preprocessing_mode, setup_response)
        self.num_peaks = max(1, int(num_peaks))

    def encode(self, recording_data: np.ndarray, sample_rate: int) -> Dict[str, Any]:
        data = _preprocess(recording_data, sample_rate, self.preprocessing_mode, self.setup_response)
        freqs, mag = _spectrum(data, sample_rate)
        selected = _select_separated_peaks(freqs, mag, self.num_peaks, TACTILE_LOW_HZ, _safe_high(sample_rate))
        return {
            "frequencies": freqs[selected],
            "magnitudes": mag[selected],
            "rms": float(np.sqrt(np.mean(data**2))),
            "sample_rate": sample_rate,
        }

    def decode(self, parameters: Dict[str, Any], duration: float, sample_rate: int) -> np.ndarray:
        num_samples = max(1, int(duration * sample_rate))
        t = np.arange(num_samples) / sample_rate
        signal_data = np.zeros(num_samples)
        for freq, mag in zip(parameters.get("frequencies", []), parameters.get("magnitudes", [])):
            phase = np.random.uniform(0.0, 2.0 * np.pi)
            signal_data += float(mag) * np.cos(2.0 * np.pi * float(freq) * t + phase)
        return _rms_match(signal_data, parameters.get("rms", 0.2))

    def get_parameter_info(self) -> Dict[str, Dict]:
        return {
            "frequencies": {"type": "array", "description": "Peak frequencies"},
            "magnitudes": {"type": "array", "description": "Peak magnitudes"},
        }


class SpectralBetaModel(TextureModel):
    """Beta-distribution envelope fitted to the strongest spectral peaks."""

    def __init__(
        self,
        num_peaks: int = 10,
        alpha_init: float = 2.0,
        beta_init: float = 5.0,
        freq_low: float = TACTILE_LOW_HZ,
        freq_high: float = TACTILE_HIGH_HZ,
        preprocessing_mode: str = "whole_signal",
        setup_response: Dict[str, Any] | None = None,
    ):
        super().__init__("sBeta", "Beta distribution spectral envelope", preprocessing_mode, setup_response)
        self.num_peaks = max(3, int(num_peaks))
        self.alpha_init = float(alpha_init)
        self.beta_init = float(beta_init)
        self.freq_low = float(freq_low)
        self.freq_high = float(freq_high)

    def encode(self, recording_data: np.ndarray, sample_rate: int) -> Dict[str, Any]:
        data = _preprocess(recording_data, sample_rate, self.preprocessing_mode, self.setup_response)
        high = _safe_high(sample_rate, self.freq_high)
        freqs, mag = _spectrum(data, sample_rate)
        selected = _select_separated_peaks(freqs, mag, self.num_peaks, self.freq_low, high)
        peak_freqs = freqs[selected]
        peak_mag = mag[selected]
        if len(peak_freqs) == 0:
            peak_freqs = np.asarray([max(self.freq_low, min(120.0, high))])
            peak_mag = np.asarray([1.0])
        log_low = np.log10(self.freq_low)
        log_high = np.log10(high)
        x = np.clip((np.log10(peak_freqs) - log_low) / max(1e-9, log_high - log_low), 1e-4, 1.0 - 1e-4)
        y = peak_mag / max(np.max(peak_mag), 1e-12)

        def objective(params):
            alpha, beta_value, scale = params
            if alpha <= 0 or beta_value <= 0 or scale <= 0:
                return 1e9
            fitted = scale * beta_dist.pdf(x, alpha, beta_value)
            return float(np.mean((y - fitted) ** 2))

        result = minimize(objective, [self.alpha_init, self.beta_init, 1.0], method="Nelder-Mead")
        alpha, beta_value, scale = result.x if result.success else [self.alpha_init, self.beta_init, 1.0]
        return {
            "alpha": float(max(alpha, 1e-3)),
            "beta": float(max(beta_value, 1e-3)),
            "scale": float(max(scale, 1e-6)),
            "peak_level": float(max(np.max(peak_mag), 1e-12)),
            "freq_low": self.freq_low,
            "freq_high": high,
            "rms": float(np.sqrt(np.mean(data**2))),
            "sample_rate": sample_rate,
        }

    def decode(self, parameters: Dict[str, Any], duration: float, sample_rate: int) -> np.ndarray:
        num_samples = max(1, int(duration * sample_rate))
        nfft = int(2 ** np.ceil(np.log2(num_samples)))
        freqs = np.fft.rfftfreq(nfft, 1.0 / sample_rate)
        low = float(parameters.get("freq_low", TACTILE_LOW_HZ))
        high = _safe_high(sample_rate, parameters.get("freq_high", TACTILE_HIGH_HZ))
        log_low = np.log10(low)
        log_high = np.log10(high)
        x = (np.log10(np.maximum(freqs, low)) - log_low) / max(1e-9, log_high - log_low)
        mag = parameters.get("scale", 1.0) * parameters.get("peak_level", 1.0) * beta_dist.pdf(np.clip(x, 1e-4, 1.0 - 1e-4), parameters.get("alpha", 2.0), parameters.get("beta", 5.0))
        mag[(freqs < low) | (freqs > high)] = 0.0
        return _random_phase_synthesis(mag, nfft, num_samples, sample_rate, parameters.get("rms", 0.2))

    def get_parameter_info(self) -> Dict[str, Dict]:
        return {"alpha": {"type": "float"}, "beta": {"type": "float"}, "scale": {"type": "float"}}


class SpectralSlopeModel(TextureModel):
    """Asymmetric triangular bandpass model centered on the dominant peak."""

    def __init__(
        self,
        freq_low: float = TACTILE_LOW_HZ,
        freq_high: float = TACTILE_HIGH_HZ,
        preprocessing_mode: str = "whole_signal",
        setup_response: Dict[str, Any] | None = None,
    ):
        super().__init__("sSlope", "Asymmetric spectral slope bandpass", preprocessing_mode, setup_response)
        self.freq_low = float(freq_low)
        self.freq_high = float(freq_high)

    def encode(self, recording_data: np.ndarray, sample_rate: int) -> Dict[str, Any]:
        data = _preprocess(recording_data, sample_rate, self.preprocessing_mode, self.setup_response)
        high = _safe_high(sample_rate, self.freq_high)
        freqs, mag = _spectrum(data, sample_rate)
        mask = (freqs >= self.freq_low) & (freqs <= high)
        band_freqs = freqs[mask]
        band_db = 20.0 * np.log10(np.maximum(mag[mask], 1e-12))
        if len(band_freqs) == 0:
            peak_freq = 120.0
            rise_order = fall_order = 1
        else:
            if len(band_db) > 7:
                window = min(51, len(band_db) if len(band_db) % 2 else len(band_db) - 1)
                if window >= 7:
                    band_db = signal.savgol_filter(band_db, window, 3)
            peak_index = int(np.argmax(band_db))
            peak_freq = float(band_freqs[peak_index])
            peak_db = float(band_db[peak_index])
            low_db = float(np.interp(self.freq_low, band_freqs, band_db))
            high_db = float(np.interp(high, band_freqs, band_db))
            rise_slope = (peak_db - low_db) / max(1e-9, np.log10(peak_freq / self.freq_low))
            fall_slope = (peak_db - high_db) / max(1e-9, np.log10(high / peak_freq))
            rise_order = int(np.clip(round(rise_slope / 20.0), 1, 8))
            fall_order = int(np.clip(round(fall_slope / 20.0), 1, 8))
        return {
            "peak_freq": peak_freq,
            "rise_order": rise_order,
            "fall_order": fall_order,
            "freq_low": self.freq_low,
            "freq_high": high,
            "rms": float(np.sqrt(np.mean(data**2))),
            "sample_rate": sample_rate,
        }

    def decode(self, parameters: Dict[str, Any], duration: float, sample_rate: int) -> np.ndarray:
        num_samples = max(1, int(duration * sample_rate))
        peak = float(np.clip(parameters.get("peak_freq", 120.0), TACTILE_LOW_HZ, _safe_high(sample_rate)))
        rise_order = int(parameters.get("rise_order", 1))
        fall_order = int(parameters.get("fall_order", 1))
        noise = np.random.randn(num_samples)
        hp_sos = signal.butter(rise_order, peak, btype="highpass", fs=sample_rate, output="sos")
        lp_sos = signal.butter(fall_order, peak, btype="lowpass", fs=sample_rate, output="sos")
        shaped = signal.sosfilt(lp_sos, signal.sosfilt(hp_sos, noise))
        shaped = _bandpass(shaped, sample_rate, parameters.get("freq_low", TACTILE_LOW_HZ), parameters.get("freq_high", TACTILE_HIGH_HZ))
        return _rms_match(shaped, parameters.get("rms", 0.2))

    def get_parameter_info(self) -> Dict[str, Dict]:
        return {
            "peak_freq": {"type": "float", "description": "Dominant peak frequency"},
            "rise_order": {"type": "int", "description": "High-pass order"},
            "fall_order": {"type": "int", "description": "Low-pass order"},
        }


def _mel_filterbank(num_filters: int, nfft: int, sample_rate: int, low_hz: float, high_hz: float) -> np.ndarray:
    def hz_to_mel(freq):
        return 2595.0 * np.log10(1.0 + freq / 700.0)

    def mel_to_hz(mel):
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    mel_points = np.linspace(hz_to_mel(low_hz), hz_to_mel(high_hz), num_filters + 2)
    hz_points = mel_to_hz(mel_points)
    bins = np.floor((nfft + 1) * hz_points / sample_rate).astype(int)
    filterbank = np.zeros((num_filters, nfft // 2 + 1))
    for index in range(1, num_filters + 1):
        left, center, right = bins[index - 1], bins[index], bins[index + 1]
        if center == left:
            center += 1
        if right == center:
            right += 1
        for k in range(left, min(center, filterbank.shape[1])):
            filterbank[index - 1, k] = (k - left) / max(1, center - left)
        for k in range(center, min(right, filterbank.shape[1])):
            filterbank[index - 1, k] = (right - k) / max(1, right - center)
    return filterbank


def _mel_band_centers(num_filters: int, nfft: int, sample_rate: int, low_hz: float, high_hz: float) -> np.ndarray:
    def hz_to_mel(freq):
        return 2595.0 * np.log10(1.0 + freq / 700.0)

    def mel_to_hz(mel):
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    mel_points = np.linspace(hz_to_mel(low_hz), hz_to_mel(high_hz), num_filters + 2)
    hz_points = mel_to_hz(mel_points)
    return np.clip(hz_points[1:-1], 0.0, sample_rate / 2.0).astype(np.float64)


def _mel_band_edges(num_filters: int, sample_rate: int, low_hz: float, high_hz: float) -> np.ndarray:
    def hz_to_mel(freq):
        return 2595.0 * np.log10(1.0 + freq / 700.0)

    def mel_to_hz(mel):
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    mel_points = np.linspace(hz_to_mel(low_hz), hz_to_mel(high_hz), num_filters + 2)
    return np.clip(mel_to_hz(mel_points), 0.0, sample_rate / 2.0).astype(np.float64)


def _random_phase_synthesis(magnitude: np.ndarray, nfft: int, num_samples: int, sample_rate: int, target_rms: float) -> np.ndarray:
    mag = np.asarray(magnitude, dtype=np.float64)
    if len(mag) != nfft // 2 + 1:
        mag = np.interp(np.linspace(0, 1, nfft // 2 + 1), np.linspace(0, 1, len(mag)), mag)
    phase = np.random.uniform(0.0, 2.0 * np.pi, len(mag))
    phase[0] = 0.0
    if len(phase) > 1:
        phase[-1] = 0.0
    spectrum = mag * np.exp(1j * phase)
    signal_data = np.fft.irfft(spectrum, n=nfft)[:num_samples]
    signal_data = _bandpass(signal_data, sample_rate)
    return _rms_match(signal_data, target_rms)


def create_texture_model(model_type: str, **kwargs) -> TextureModel:
    """Factory function for texture models."""
    key = model_type.strip().lower().replace(" ", "_")
    common = {
        "preprocessing_mode": kwargs.get("preprocessing_mode", "whole_signal"),
        "setup_response": kwargs.get("setup_response"),
    }
    if key in ("raw", "raw_signal"):
        return RawSignalModel(**common)
    if key in ("ar", "arma", "auto_regression"):
        return AutoRegressionModel(kwargs.get("order", kwargs.get("ar_order", 6)), **common)
    if key == "mfcc":
        return MFCCModel(
            kwargs.get("num_coefficients", 10),
            kwargs.get("num_filters", 26),
            kwargs.get("frame_size", 0.025),
            kwargs.get("frame_stride", 0.010),
            **common,
        )
    if key in ("speak", "spectral_peak"):
        return SpectralPeakModel(kwargs.get("num_peaks", 10), **common)
    if key in ("sbeta", "spectral_beta", "spectral"):
        return SpectralBetaModel(
            kwargs.get("num_peaks", 10),
            kwargs.get("alpha_init", 2.0),
            kwargs.get("beta_init", 5.0),
            kwargs.get("freq_low", TACTILE_LOW_HZ),
            kwargs.get("freq_high", TACTILE_HIGH_HZ),
            **common,
        )
    if key in ("sslope", "spectral_slope", "slope", "filter", "reduced"):
        return SpectralSlopeModel(kwargs.get("freq_low", TACTILE_LOW_HZ), kwargs.get("freq_high", TACTILE_HIGH_HZ), **common)
    raise ValueError(f"Unknown model type: {model_type}")
