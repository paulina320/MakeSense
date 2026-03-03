"""
Rendering Module
Handles texture synthesis and playback.
"""

import numpy as np
from typing import Optional, List
from dataclasses import dataclass
from .recording import Recording
from .texture_models import TextureModel
from .characterization import ActuatorCharacterization
from .compensation import CompensationFilter, Compensator


@dataclass
class RenderSettings:
    """Settings for texture rendering."""
    
    texture: Optional[Recording] = None
    model_type: str = "raw"  # raw, spectral, reduced, filter
    model_parameters: dict = None
    actuator: Optional[ActuatorCharacterization] = None
    compensation: Optional[CompensationFilter] = None
    gain_db: float = -3.0
    playback_sample_rate: int = 44100
    apply_compensation: bool = False


class Renderer:
    """Renders textures for haptic playback."""
    
    def __init__(self, sample_rate: int = 44100):
        """Initialize renderer."""
        self.sample_rate = sample_rate
        self.compensator = Compensator(sample_rate)
        self.playback_buffer = None
    
    def render(
        self,
        texture: Recording,
        model: TextureModel,
        duration: Optional[float] = None,
        gain_db: float = -3.0,
        apply_actuator_response: bool = False,
        actuator: Optional[ActuatorCharacterization] = None,
        apply_compensation: bool = False,
        compensation: Optional[CompensationFilter] = None,
    ) -> np.ndarray:
        """
        Render texture with specified settings.
        
        Args:
            texture: Input recording
            model: Texture model to use
            duration: Duration to render (None = use texture duration)
            gain_db: Output gain in dB
            apply_actuator_response: Apply actuator transfer function
            actuator: ActuatorCharacterization object
            apply_compensation: Apply compensation filter
            compensation: CompensationFilter object
        
        Returns:
            Rendered signal
        """
        # Get model representation
        if isinstance(texture, Recording):
            model_params = model.encode(texture.data, texture.sample_rate)
            if duration is None:
                duration = texture.duration
        else:
            # Assume it's raw data
            model_params = model.encode(texture, self.sample_rate)
            if duration is None:
                duration = len(texture) / self.sample_rate
        
        # Decode from model
        rendered = model.decode(model_params, duration, self.sample_rate)
        
        # Apply actuator transfer function
        if apply_actuator_response and actuator:
            rendered = self._apply_actuator_response(rendered, actuator)
        
        # Apply compensation
        if apply_compensation and compensation:
            rendered = self.compensator.apply_frequency_domain(rendered, compensation)
        
        # Apply gain
        gain_linear = 10 ** (gain_db / 20)
        rendered = rendered * gain_linear
        
        # Clip to prevent distortion
        rendered = np.clip(rendered, -1.0, 1.0)
        
        self.playback_buffer = rendered
        return rendered
    
    def _apply_actuator_response(
        self,
        signal_data: np.ndarray,
        actuator: ActuatorCharacterization,
    ) -> np.ndarray:
        """
        Apply actuator frequency response to signal.
        
        Args:
            signal_data: Input signal
            actuator: Actuator characterization
        
        Returns:
            Signal with actuator response applied
        """
        from scipy import signal, fftpack
        
        # FFT of signal
        fft_size = 2 * len(signal_data)
        padded = np.zeros(fft_size)
        padded[:len(signal_data)] = signal_data
        
        fft_signal = fftpack.fft(padded)
        
        # Interpolate actuator response to FFT frequencies
        fft_freqs = np.fft.rfftfreq(fft_size, 1 / self.sample_rate)
        H_actuator = np.interp(
            fft_freqs,
            actuator.frequencies,
            actuator.magnitude * np.exp(1j * actuator.phase),
            left=1.0,
            right=1.0,
        )
        
        # Apply actuator response
        fft_signal[:len(H_actuator)] *= H_actuator
        
        # IFFT
        result = np.real(fftpack.ifft(fft_signal))[:len(signal_data)]
        
        return result
    
    def get_output_spectrum(
        self,
        rendered: np.ndarray,
    ) -> tuple:
        """
        Get frequency spectrum of rendered output.
        
        Returns:
            Tuple of (frequencies, magnitude spectrum in dB)
        """
        from .fft_tools import compute_fft
        
        freqs, mag_db = compute_fft(rendered, self.sample_rate, fft_size=4096)
        return freqs, mag_db
    
    def get_playback_waveform(
        self,
        duration: float = 0.1,
    ) -> Optional[np.ndarray]:
        """
        Get current playback waveform for visualization.
        
        Args:
            duration: Duration to display in seconds
        
        Returns:
            Waveform samples
        """
        if self.playback_buffer is None:
            return None
        
        num_samples = int(duration * self.sample_rate)
        return self.playback_buffer[:num_samples]


class PlaybackController:
    """Controls real-time playback of rendered textures."""
    
    def __init__(self, sample_rate: int = 44100, buffer_size: int = 2048):
        """Initialize playback controller."""
        self.sample_rate = sample_rate
        self.buffer_size = buffer_size
        self.is_playing = False
        self.loop_enabled = False
        self.current_position = 0
        self.playback_data = None
        self.renderer = Renderer(sample_rate)
    
    def load_texture(self, rendered_signal: np.ndarray) -> None:
        """Load texture for playback."""
        self.playback_data = rendered_signal
        self.current_position = 0
    
    def start(self) -> None:
        """Start playback."""
        self.is_playing = True
        self.current_position = 0
    
    def stop(self) -> None:
        """Stop playback."""
        self.is_playing = False
    
    def pause(self) -> None:
        """Pause playback."""
        self.is_playing = False
    
    def resume(self) -> None:
        """Resume playback."""
        self.is_playing = True
    
    def get_next_block(self) -> np.ndarray:
        """
        Get next block of audio for playback.
        
        Returns:
            Audio block of size buffer_size
        """
        if not self.is_playing or self.playback_data is None:
            return np.zeros(self.buffer_size)
        
        block = np.zeros(self.buffer_size)
        
        remaining = len(self.playback_data) - self.current_position
        to_read = min(self.buffer_size, remaining)
        
        block[:to_read] = self.playback_data[
            self.current_position:self.current_position + to_read
        ]
        
        self.current_position += to_read
        
        # Handle looping
        if self.loop_enabled and to_read < self.buffer_size:
            self.current_position = 0
            remaining_in_block = self.buffer_size - to_read
            
            if len(self.playback_data) > 0:
                to_read_loop = min(remaining_in_block, len(self.playback_data))
                block[to_read:to_read + to_read_loop] = self.playback_data[:to_read_loop]
        
        return block
    
    def set_gain(self, gain_db: float) -> None:
        """Set playback gain."""
        if self.playback_data is not None:
            gain_linear = 10 ** (gain_db / 20)
            self.playback_data = self.playback_data * gain_linear
    
    def set_loop(self, enable: bool) -> None:
        """Enable/disable looping."""
        self.loop_enabled = enable
