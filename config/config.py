"""
Configuration module for Haptic Software.
Defines default parameters, device presets, and global settings.
"""

# ============================================================================
# AUDIO & RECORDING PARAMETERS
# ============================================================================
AUDIO_CONFIG = {
    "default_sample_rate": 44100,  # Hz
    "default_duration": 5.0,  # seconds
    "channels": 1,  # Mono
}

# ============================================================================
# DEVICE PRESETS
# ============================================================================
ACTUATOR_PRESETS = {
    "Haptuator": {
        "name": "Haptuator",
        "type": "actuator",
        "default_frequency_range": (10, 300),  # Hz
        "impedance_nominal": 4.0,  # Ohms
    },
    "LRA": {
        "name": "LRA (Linear Resonant Actuator)",
        "type": "actuator",
        "default_frequency_range": (50, 300),  # Hz
        "impedance_nominal": 100.0,  # Ohms
    },
}

SENSOR_PRESETS = {
    "ADX358": {
        "name": "ADX358 Accelerometer",
        "type": "accelerometer",
        "sensitivity": 0.032,  # V/g
        "range": 16,  # +/- 16g
        "sample_rate": 44100,  # Hz
    },
}

# ============================================================================
# TEXTURE MODELING
# ============================================================================
TEXTURE_MODEL_CONFIG = {
    "raw_signal": {
        "name": "Raw Signal",
        "description": "Unprocessed recording",
    },
    "arma": {
        "name": "ARMA Model",
        "description": "Autoregressive Moving Average model",
        "default_parameters": {
            "ar_order": 6,  # Autoregressive order
            "ma_order": 1,  # Moving average order
        }
    },
    "mfcc": {
        "name": "MFCC Model",
        "description": "Mel-frequency cepstral coefficients",
        "default_parameters": {
            "num_coefficients": 10,
            "frame_size": 0.025,  # seconds (25 ms)
            "frame_stride": 0.010,  # seconds (10 ms)
            "num_filters": 26,
            "fft_size": 512,
            "low_freq": 20,
            "high_freq": 1000,
        }
    },
    "speak": {
        "name": "sPeak Model",
        "description": "Peak-based spectral model",
        "default_parameters": {
            "num_peaks": 10,
        }
    },
    "sbeta": {
        "name": "sBeta Model",
        "description": "Beta distribution spectral model",
        "default_parameters": {
            "num_peaks": 10,
            "alpha_init": 2.0,
            "beta_init": 5.0,
            "freq_low": 20,
            "freq_high": 1000,
        }
    },
    "spectral_slope": {
        "name": "Spectral Slope Model",
        "description": "Roll-off based spectral shaping filter",
        "default_parameters": {
            "window_size": 3,
            "ref_freq_low": 10,
            "ref_freq_high": 1000,
        }
    },
}

TEXTURE_MODEL_PARAMETERS = {
    "frequency_band_limits": (10, 8000),  # Hz
    "default_gain": 1.0,
    "model_complexity_range": (1, 50),  # Parameter count range
}

# ============================================================================
# ACTUATOR CHARACTERIZATION
# ============================================================================
CHARACTERIZATION_CONFIG = {
    "excitation_types": {
        "sweep": {
            "name": "Frequency Sweep",
            "default_start_freq": 10,  # Hz
            "default_end_freq": 300,  # Hz
            "default_duration": 2.0,  # seconds
        },
        "white_noise": {
            "name": "White Noise",
            "default_duration": 2.0,  # seconds
        },
        "impulse": {
            "name": "Impulse",
            "peak_amplitude": 1.0,
            "duration": 0.001,  # seconds
        },
    },
    "fft_resolution": 2048,  # FFT bins
    "window_function": "hann",  # or "hamming", "blackman"
}

# ============================================================================
# COMPENSATION
# ============================================================================
COMPENSATION_CONFIG = {
    "regularization_epsilon": 1e-6,  # Numerical stability
    "max_gain_db": 20.0,  # dB, limit at resonance
    "frequency_smoothing_window": 51,  # For smoothing inverse filter
}

# ============================================================================
# RENDERING & PLAYBACK
# ============================================================================
RENDERING_CONFIG = {
    "playback_sample_rate": 44100,  # Hz
    "playback_channels": 1,  # Mono
    "default_gain": 0.5,  # 0.0 to 1.0
    "buffer_size": 2048,  # Samples
}

# ============================================================================
# EVALUATION / DISCUSSION
# ============================================================================
EVALUATION_CONFIG = {
    "rating_scales": {
        "pleasantness": {
            "min": 1,
            "max": 10,
            "label": "Pleasantness",
        },
        "realism": {
            "min": 1,
            "max": 10,
            "label": "Realism",
        },
        "intensity": {
            "min": 1,
            "max": 10,
            "label": "Intensity",
        },
    },
    "comparison_modes": ["Blind A/B", "Reference", "Sequential"],
}

# ============================================================================
# UI CONFIGURATION
# ============================================================================
UI_CONFIG = {
    "app_name": "MakeSense - Why Doesn't This Texture Feel Right?",
    "window_width": 1400,
    "window_height": 900,
    "dark_mode": False,
    "log_level": "INFO",
}

# ============================================================================
# VISUALIZATION
# ============================================================================
VISUALIZATION_CONFIG = {
    "time_domain": {
        "show_grid": True,
        "line_width": 1.5,
    },
    "frequency_domain": {
        "fft_size": 4096,
        "log_scale": True,
        "y_limit_db": (-60, 0),
    },
    "spectrogram": {
        "window_size": 512,
        "overlap": 0.75,
        "cmap": "viridis",
    },
    "colors": {
        "original": "#1f77b4",
        "processed": "#ff7f0e",
        "compensated": "#2ca02c",
        "actuator": "#d62728",
    },
}

# ============================================================================
# HARDWARE INTERFACE
# ============================================================================
HARDWARE_CONFIG = {
    "serial_timeout": 2.0,  # seconds
    "daq_sampling_rate": 44100,  # Hz
    "daq_channels": 1,
    "device_backend": "haptic_device",  # "mock" or "haptic_device"
}

HAPTIC_DEVICE_CONFIG = {
    "backend": "haptic_device",  # "mock" or "haptic_device"
    "default_port": None,
    "baudrate": 921600,
    "serial_timeout": 0.5,
    "command_timeout": 3.0,
    "frame_queue_size": 64,
    "render_frame_samples": 128,
    "default_sample_rate": 44100,
    "default_channels": [0],
    "channels": [
        {
            "pin": pin,
            "role": "high_z",
            "differential_partner": None,
            "adc_range": "0_2_5",
            "dac_range": "0_10",
            "reference": "internal",
            "averaging": 1,
            "stream_enabled": False,
        }
        for pin in range(20)
    ],
}

# ============================================================================
# THREAD SAFETY & PERFORMANCE
# ============================================================================
THREADING_CONFIG = {
    "worker_thread_priority": "high",
    "buffer_size": 4096,  # Samples
    "ring_buffer_capacity": 4,  # Number of buffers
}

