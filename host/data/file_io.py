"""
File I/O Module
Handles file operations for various data types.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import os
import numpy as np
import json
from typing import Optional

from processing.recording import Recording, RecordingMetadata


class FileIO:
    """File I/O operations for recordings and processed data."""
    
    @staticmethod
    def save_wav(
        filepath: str,
        data: np.ndarray,
        sample_rate: int,
    ) -> None:
        """
        Save audio data to WAV file.
        
        Args:
            filepath: Output file path
            data: Audio data [samples] or [samples, channels]
            sample_rate: Sampling rate in Hz
        """
        try:
            import scipy.io.wavfile as wavfile
            
            # Ensure int16 range
            if data.dtype != np.int16:
                # Normalize to [-1, 1] and convert to int16
                max_val = np.max(np.abs(data))
                if max_val > 0:
                    data = (data / max_val * 32767).astype(np.int16)
                else:
                    data = data.astype(np.int16)
            
            # Create directory if needed
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            wavfile.write(filepath, sample_rate, data)
        except ImportError:
            raise ImportError("scipy required for WAV file operations")
    
    @staticmethod
    def load_wav(filepath: str) -> tuple:
        """
        Load audio from WAV file.
        
        Args:
            filepath: Input file path
        
        Returns:
            Tuple of (data, sample_rate)
        """
        try:
            import scipy.io.wavfile as wavfile
            sample_rate, data = wavfile.read(filepath)
            
            # Convert to float
            if data.dtype == np.int16:
                data = data.astype(np.float32) / 32768.0
            elif data.dtype == np.int32:
                data = data.astype(np.float32) / 2147483648.0
            
            return data, sample_rate
        except ImportError:
            raise ImportError("scipy required for WAV file operations")
    
    @staticmethod
    def save_csv(filepath: str, data: np.ndarray) -> None:
        """
        Save data to CSV file.
        
        Args:
            filepath: Output file path
            data: Data array
        """
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        np.savetxt(filepath, data, delimiter=',')
    
    @staticmethod
    def load_csv(filepath: str) -> np.ndarray:
        """Load data from CSV file."""
        return np.loadtxt(filepath, delimiter=',')
    
    @staticmethod
    def save_npz(filepath: str, **arrays) -> None:
        """
        Save multiple arrays to NPZ file.
        
        Args:
            filepath: Output file path
            **arrays: Named arrays to save
        """
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        np.savez(filepath, **arrays)
    
    @staticmethod
    def load_npz(filepath: str) -> dict:
        """Load data from NPZ file."""
        data = np.load(filepath, allow_pickle=True)
        return {key: data[key] for key in data.files}
    
    @staticmethod
    def save_json(filepath: str, data: dict) -> None:
        """Save dictionary to JSON file."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    
    @staticmethod
    def load_json(filepath: str) -> dict:
        """Load JSON file."""
        with open(filepath, 'r') as f:
            return json.load(f)
    
    @staticmethod
    def save_recording(
        filepath: str,
        recording: Recording,
        format: str = "wav",
    ) -> None:
        """
        Save recording to file.
        
        Args:
            filepath: Output file path
            recording: Recording object
            format: File format ('wav', 'csv', 'npz')
        """
        if format == "wav":
            FileIO.save_wav(filepath, recording.data, recording.sample_rate)
        elif format == "csv":
            FileIO.save_csv(filepath, recording.data)
        elif format == "npz":
            channel_names = recording.metadata.channel_names or []
            FileIO.save_npz(
                filepath,
                data=recording.data,
                sample_rate=recording.sample_rate,
                channel_names=np.asarray(channel_names, dtype=object),
            )
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    @staticmethod
    def load_recording(filepath: str, format: str = "auto") -> Recording:
        """
        Load recording from file.
        
        Args:
            filepath: Input file path
            format: File format ('auto', 'wav', 'csv', 'npz')
        
        Returns:
            Recording object
        """
        if format == "auto":
            ext = Path(filepath).suffix.lower()
            format = ext.lstrip('.')
        
        metadata = RecordingMetadata()
        
        if format == "wav":
            data, sample_rate = FileIO.load_wav(filepath)
        elif format == "csv":
            data = FileIO.load_csv(filepath)
            sample_rate = 44100  # Default
        elif format == "npz":
            npz_data = FileIO.load_npz(filepath)
            data = npz_data.get('data')
            sample_rate = int(npz_data.get('sample_rate', 44100))
            if 'channel_names' in npz_data:
                metadata.channel_names = [str(name) for name in npz_data['channel_names'].tolist()]
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        return Recording(data, sample_rate, metadata)
