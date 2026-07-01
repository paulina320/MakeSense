"""
Processing package initialization.
"""

from .fft_tools import (
    compute_fft,
    compute_spectrogram,
    compute_transfer_function,
    smooth_signal,
    inverse_filter,
)
from .recording import Recording, RecordingMetadata, RecordingBuffer
from .texture_models import (
    TextureModel,
    RawSignalModel,
    AutoRegressionModel,
    MFCCModel,
    SpectralPeakModel,
    SpectralBetaModel,
    SpectralSlopeModel,
    create_texture_model,
)
from .characterization import Characterizer, ActuatorCharacterization
from .compensation import Compensator, CompensationFilter
from .rendering import Renderer, PlaybackController

__all__ = [
    "compute_fft",
    "compute_spectrogram",
    "compute_transfer_function",
    "find_resonance_peaks",
    "smooth_signal",
    "inverse_filter",
    "Recording",
    "RecordingMetadata",
    "RecordingBuffer",
    "TextureModel",
    "RawSignalModel",
    "AutoRegressionModel",
    "MFCCModel",
    "SpectralPeakModel",
    "SpectralBetaModel",
    "SpectralSlopeModel",
    "create_texture_model",
    "Characterizer",
    "ActuatorCharacterization",
    "Compensator",
    "CompensationFilter",
    "Renderer",
    "PlaybackController",
]
