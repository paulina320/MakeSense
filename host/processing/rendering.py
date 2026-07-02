"""
Rendering Module
Handles playback preparation for haptic rendering.
"""

import numpy as np
from .compensation import Compensator


WINDOW_TYPES = (
    "off",
    "full_hann_50",
    "linear",
    "half_hann",
    "smoothstep",
    "smootherstep",
    "equal_power",
)


def boundary_crossfade_gains(sample_count: int, window_type: str) -> tuple[np.ndarray, np.ndarray]:
    """Return fade-out and fade-in gains for a loop-boundary crossfade."""
    sample_count = max(1, int(sample_count))
    window_type = str(window_type).lower()
    if window_type not in WINDOW_TYPES:
        raise ValueError(f"Unknown boundary window: {window_type}")

    x = np.arange(sample_count, dtype=np.float64) / sample_count
    if window_type == "off":
        fade_in = np.zeros(sample_count, dtype=np.float64)
    elif window_type == "linear":
        fade_in = x
    elif window_type in ("half_hann", "full_hann_50"):
        fade_in = 0.5 - 0.5 * np.cos(np.pi * x)
    elif window_type == "smoothstep":
        fade_in = 3.0 * x**2 - 2.0 * x**3
    elif window_type == "smootherstep":
        fade_in = 6.0 * x**5 - 15.0 * x**4 + 10.0 * x**3
    else:
        fade_in = np.sin(0.5 * np.pi * x)

    fade_out = (
        np.cos(0.5 * np.pi * x)
        if window_type == "equal_power"
        else 1.0 - fade_in
    )
    return fade_out.astype(np.float32), fade_in.astype(np.float32)


def make_boundary_crossfade_loop(
    signal_data: np.ndarray,
    sample_rate: int,
    duration_ms: float = 20.0,
    window_type: str = "full_hann_50",
) -> np.ndarray:
    """Join a signal's tail and head with a short selectable crossfade.

    Only the boundary is changed. The overlapping tail and head occupy one
    shared region, so the resulting loop cycle is shorter by the crossfade
    duration (20 ms turns a 400 ms source into a 380 ms cycle).
    """
    signal_data = np.asarray(signal_data, dtype=np.float32).reshape(-1)
    sample_count = len(signal_data)
    if sample_count < 2 or window_type == "off":
        return signal_data.copy()

    if window_type == "full_hann_50":
        hop = max(1, sample_count // 2)
        positions = np.arange(sample_count, dtype=np.float64)
        window = 0.5 - 0.5 * np.cos(2.0 * np.pi * positions / sample_count)
        output = np.zeros(hop, dtype=np.float64)
        weight_sum = np.zeros(hop, dtype=np.float64)
        phases = np.arange(sample_count) % hop
        np.add.at(output, phases, signal_data * window)
        np.add.at(weight_sum, phases, window)
        np.divide(output, weight_sum, out=output, where=weight_sum > 0.0)
        return output.astype(np.float32)

    overlap = max(1, int(round(float(sample_rate) * float(duration_ms) / 1000.0)))
    overlap = min(overlap, sample_count // 2)
    fade_out, fade_in = boundary_crossfade_gains(overlap, window_type)
    crossfade = signal_data[-overlap:] * fade_out + signal_data[:overlap] * fade_in
    middle = signal_data[overlap:-overlap]
    return np.concatenate((middle, crossfade)).astype(np.float32, copy=False)


class Renderer:
    """Small owner for processing helpers used by the rendering UI."""
    
    def __init__(self, sample_rate: int = 10000):
        """Initialize renderer."""
        self.sample_rate = sample_rate
        self.compensator = Compensator(sample_rate)


class PlaybackController:
    """Controls real-time playback of rendered textures."""
    
    def __init__(self, sample_rate: int = 10000, buffer_size: int = 2048):
        """Initialize playback controller."""
        self.sample_rate = sample_rate
        self.buffer_size = buffer_size
        self.is_playing = False
        self.loop_enabled = False
        self.current_position = 0
        self.original_data = None
        self.playback_data = None
        self.gain_db = 0.0
    
    def load_texture(self, rendered_signal: np.ndarray) -> None:
        """Store the source unchanged and create a gain-adjusted playback copy."""
        self.original_data = np.array(
            rendered_signal,
            dtype=np.float32,
            copy=True,
        ).reshape(-1)
        self.original_data.setflags(write=False)
        self._update_playback_data()
        self.current_position = 0

    def _update_playback_data(self) -> None:
        """Always apply gain to the original signal, never to prior output."""
        if self.original_data is None:
            self.playback_data = None
            return
        gain_linear = 10 ** (self.gain_db / 20)
        self.playback_data = np.clip(
            self.original_data * gain_linear,
            -1.0,
            1.0,
        ).astype(np.float32, copy=False)
    
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
        """Recreate playback data from the unchanged source at this gain."""
        self.gain_db = float(gain_db)
        self._update_playback_data()
    
    def set_loop(self, enable: bool) -> None:
        """Enable/disable looping."""
        self.loop_enabled = enable
