"""
Texture Models Module
Provides various texture representation models.
"""

import numpy as np
from abc import ABC, abstractmethod
from typing import Dict, Any
from .fft_tools import compute_fft, smooth_signal, inverse_filter
from scipy import signal


class TextureModel(ABC):
    """Abstract base class for texture models."""
    
    def __init__(self, name: str, description: str):
        """Initialize texture model."""
        self.name = name
        self.description = description
        self.parameters: Dict[str, Any] = {}
    
    @abstractmethod
    def encode(self, recording_data: np.ndarray, sample_rate: int) -> Dict[str, Any]:
        """
        Encode recording into model parameters.
        
        Returns:
            Dictionary with model parameters
        """
        pass
    
    @abstractmethod
    def decode(self, parameters: Dict[str, Any], duration: float, sample_rate: int) -> np.ndarray:
        """
        Decode model parameters back to signal.
        
        Returns:
            Reconstructed signal
        """
        pass
    
    @abstractmethod
    def get_parameter_info(self) -> Dict[str, Dict]:
        """Get information about model parameters."""
        pass


class RawSignalModel(TextureModel):
    """Raw, unprocessed signal model."""
    
    def __init__(self):
        super().__init__("Raw Signal", "Unprocessed recording")
    
    def encode(self, recording_data: np.ndarray, sample_rate: int) -> Dict[str, Any]:
        """Store raw signal."""
        if recording_data.ndim > 1:
            recording_data = recording_data[:, 0]
        
        return {
            "signal": recording_data.copy(),
            "sample_rate": sample_rate,
        }
    
    def decode(self, parameters: Dict[str, Any], duration: float, sample_rate: int) -> np.ndarray:
        """Return raw signal."""
        return parameters.get("signal", np.array([]))
    
    def get_parameter_info(self) -> Dict[str, Dict]:
        """Get parameter information."""
        return {
            "signal": {"type": "array", "description": "Raw audio signal"},
        }


class SpectralEnvelopeModel(TextureModel):
    """Spectral envelope representation."""
    
    def __init__(self, num_bands: int = 32):
        super().__init__("Spectral Envelope Model", "Frequency-based envelope")
        self.num_bands = num_bands
        self.parameters = {"num_bands": num_bands}
    
    def encode(self, recording_data: np.ndarray, sample_rate: int) -> Dict[str, Any]:
        """Extract spectral envelope."""
        if recording_data.ndim > 1:
            recording_data = recording_data[:, 0]
        
        # Compute FFT
        freqs, mag_db = compute_fft(recording_data, sample_rate, fft_size=4096)
        
        # Bin into bands
        band_edges = np.logspace(np.log10(20), np.log10(sample_rate/2), self.num_bands + 1)
        envelope = np.zeros(self.num_bands)
        
        for i in range(self.num_bands):
            mask = (freqs >= band_edges[i]) & (freqs < band_edges[i+1])
            if np.any(mask):
                envelope[i] = np.max(mag_db[mask])
        
        return {
            "envelope": envelope,
            "band_edges": band_edges,
            "num_bands": self.num_bands,
        }
    
    def decode(self, parameters: Dict[str, Any], duration: float, sample_rate: int) -> np.ndarray:
        """Reconstruct from envelope."""
        envelope = parameters.get("envelope", np.zeros(self.num_bands))
        num_samples = int(duration * sample_rate)
        
        # Simple synthesis: noise filtered by envelope
        noise = np.random.randn(num_samples)
        
        # Apply envelope via filtering (simplified)
        return noise * np.mean(10 ** (envelope / 20))
    
    def get_parameter_info(self) -> Dict[str, Dict]:
        """Get parameter information."""
        return {
            "envelope": {"type": "array", "shape": (self.num_bands,), "description": "Magnitude envelope per band"},
        }


class ReducedParameterModel(TextureModel):
    """Reduced parameter model using principal components."""
    
    def __init__(self, num_parameters: int = 10):
        super().__init__("Reduced / Low-Parameter Model", "Simplified parametric representation")
        self.num_parameters = num_parameters
        self.parameters = {"num_parameters": num_parameters}
    
    def encode(self, recording_data: np.ndarray, sample_rate: int) -> Dict[str, Any]:
        """Extract principal components."""
        if recording_data.ndim > 1:
            recording_data = recording_data[:, 0]
        
        # Normalize
        recording_normalized = recording_data / (np.max(np.abs(recording_data)) + 1e-10)
        
        # Simple DCT-based compression
        from scipy.fftpack import dct
        dct_coeff = dct(recording_normalized)
        
        # Keep top N coefficients
        params = np.zeros(self.num_parameters)
        params[:min(len(dct_coeff), self.num_parameters)] = dct_coeff[:self.num_parameters]
        
        return {
            "parameters": params,
            "num_parameters": self.num_parameters,
        }
    
    def decode(self, parameters: Dict[str, Any], duration: float, sample_rate: int) -> np.ndarray:
        """Reconstruct from parameters."""
        from scipy.fftpack import idct
        
        params = parameters.get("parameters", np.zeros(self.num_parameters))
        num_samples = int(duration * sample_rate)
        
        # Pad parameters to signal length
        padded = np.zeros(num_samples)
        padded[:len(params)] = params
        
        # Inverse DCT
        reconstructed = idct(padded)
        
        return reconstructed / (np.max(np.abs(reconstructed)) + 1e-10)
    
    def get_parameter_info(self) -> Dict[str, Dict]:
        """Get parameter information."""
        return {
            "parameters": {"type": "array", "shape": (self.num_parameters,), "description": "DCT coefficients"},
        }


class FilterBasedModel(TextureModel):
    """Filter cascade representation."""
    
    def __init__(self, filter_order: int = 8):
        super().__init__("Filter-Based Representation", "Filter cascade approximation")
        self.filter_order = filter_order
        self.parameters = {"filter_order": filter_order}
    
    def encode(self, recording_data: np.ndarray, sample_rate: int) -> Dict[str, Any]:
        """Design filter from recording."""
        if recording_data.ndim > 1:
            recording_data = recording_data[:, 0]
        
        # Compute spectrum
        freqs, mag_db = compute_fft(recording_data, sample_rate, fft_size=4096)
        
        # Simple spectral shaping filter
        normalized_freqs = freqs / (sample_rate / 2)
        normalized_freqs = np.clip(normalized_freqs, 0.001, 0.999)
        
        # Design IIR filter to match spectrum
        try:
            b, a = signal.butter(self.filter_order, 0.5)
        except:
            b, a = [1.0], [1.0]
        
        return {
            "b": b,
            "a": a,
            "filter_order": self.filter_order,
        }
    
    def decode(self, parameters: Dict[str, Any], duration: float, sample_rate: int) -> np.ndarray:
        """Synthesize with filter."""
        b = parameters.get("b", [1.0])
        a = parameters.get("a", [1.0])
        
        num_samples = int(duration * sample_rate)
        
        # Excitation: white noise
        excitation = np.random.randn(num_samples)
        
        # Apply filter
        filtered = signal.lfilter(b, a, excitation)
        
        # Normalize
        return filtered / (np.max(np.abs(filtered)) + 1e-10)
    
    def get_parameter_info(self) -> Dict[str, Dict]:
        """Get parameter information."""
        return {
            "b": {"type": "array", "description": "Filter numerator coefficients"},
            "a": {"type": "array", "description": "Filter denominator coefficients"},
        }


# Factory function
def create_texture_model(model_type: str, **kwargs) -> TextureModel:
    """
    Factory function to create texture models.
    
    Args:
        model_type: Type of model ('raw', 'spectral', 'reduced', 'filter')
        **kwargs: Model-specific parameters
    
    Returns:
        TextureModel instance
    """
    if model_type == "raw":
        return RawSignalModel()
    elif model_type == "spectral":
        return SpectralEnvelopeModel(kwargs.get("num_bands", 32))
    elif model_type == "reduced":
        return ReducedParameterModel(kwargs.get("num_parameters", 10))
    elif model_type == "filter":
        return FilterBasedModel(kwargs.get("filter_order", 8))
    else:
        raise ValueError(f"Unknown model type: {model_type}")
