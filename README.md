# Haptic Software - Texture Recording & Rendering

A PyQt6-based application for recording, modeling, characterizing, and rendering haptic textures. This software implements a complete pipeline for haptic device research and development.

## Architecture

### Modular Design
```
haptic-software/
├── ui/                          # PyQt6 UI widgets
│   ├── main_window.py          # Main application window
│   ├── recording_widget.py
│   ├── model_widget.py
│   ├── characterization_widget.py
│   ├── compensation_widget.py
│   ├── rendering_widget.py
│   └── evaluation_widget.py
├── processing/                  # Signal processing (pure Python)
│   ├── fft_tools.py            # Frequency domain analysis
│   ├── recording.py            # Recording data structures
│   ├── texture_models.py       # Texture representations
│   ├── characterization.py     # Actuator characterization
│   ├── compensation.py         # Compensation filters
│   └── rendering.py            # Synthesis and playback
├── hardware/                    # Hardware abstraction
│   ├── audio_interface.py      # Audio I/O
│   ├── daq_interface.py        # DAQ abstraction
│   └── accelerometer_interface.py
├── data/                        # Data management
│   ├── file_io.py              # File operations
│   └── project_manager.py      # Project management
├── visualization/              # Plotting utilities
│   └── plot_widgets.py         # Matplotlib/PyQtGraph wrappers
├── config/
│   └── config.py               # Configuration parameters
├── main.py                      # Application entry point
└── requirements.txt            # Python dependencies
```

## Installation

### 1. Clone Repository
```bash
cd /haptic-software
```

### 2. Create Virtual Environment (recommended)
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### Optional: Hardware Support
For specific hardware, install additional packages:
```bash
# For NI DAQ devices
pip install nidaqmx

# For serial communication (Arduino, accelerometer)
pip install pyserial
```

## Usage

### Running the Application
```bash
python main.py
```

## Configuration

Edit `config/config.py` to customize:
- Default audio parameters (sample rate, duration)
- Device presets (Haptuator, LRA)
- Model parameters (bands, complexity)
- Compensation settings (regularization, max gain)
- UI settings (window size, dark mode)

### Supported DAQ
- Mock (testing)
- National Instruments (nidaqmx)
- Custom implementations

### Supported Actuators
- Haptuator
- LRA (Linear Resonant Actuator)
- Custom via plugin interface

## File Formats

### Recordings
- WAV: Standard audio format
- CSV: Comma-separated values
- NPZ: NumPy compressed archive

### Session Data
- JSON: Project metadata and session state
- NPZ: Transfer functions and filter coefficients

## Development

**Version**: 0.1  
**Last Updated**: March 2, 2026  
