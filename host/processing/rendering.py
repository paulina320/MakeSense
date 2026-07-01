"""
Rendering Module
Handles playback preparation for haptic rendering.
"""

import numpy as np
from .compensation import Compensator


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
