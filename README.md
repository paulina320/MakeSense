# Why Doesn’t This Texture Feel Right? A Hands-On Workshop on Data-Driven Haptic Texture Reproduction and Typical Pitfall

"Why Doesn't This Texture Feel Right?" is a PyQt6 workshop application for recording, modeling,
characterizing, compensating, and rendering haptic textures with the MakeSense
hardware kit.

The interface is organized as a guided pipeline:

1. Record a texture or load an existing recording.
2. Select and inspect a texture model.
3. Characterize the actuator and sensing path.
4. Generate or load a compensation filter.
5. Prepare and play the result through a workshop actuator.

## Repository layout

```text
haptic-workshop/
├── firmware/
│   └── stm32_haptic_device/        # Active STM32 firmware
├── main.py                         # Application entry point
├── ui/                             # PyQt6 interface and theme assets
├── processing/                     # DSP and texture models
├── hardware/                       # Serial device and mock interfaces
├── data/                           # Recording file I/O
├── visualization/                  # Plotting helpers
├── config/                         # Application and hardware settings
├── compensation_filters/           # Bundled compensation presets
├── scripts/                        # Hardware and throughput diagnostics
├── tests/                          # Automated tests
├── requirements.txt
└── PACKAGING.md
```

## Installation from source

Run these commands from the repository root.

### Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

### Linux

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python main.py
```

Linux may also require PortAudio and Qt platform libraries. See
[PACKAGING.md](PACKAGING.md) for the Ubuntu/Debian packages used by packaged
builds.

## Hardware

The default backend is the serial MakeSense haptic device:

```python
HAPTIC_DEVICE_CONFIG["backend"] = "haptic_device"
```

The active firmware is located at:

```text
firmware/stm32_haptic_device
```

After flashing the firmware:

1. Connect the board over USB.
2. Open the **Device** tab.
3. Select the serial port under **Detailed Info**, if it was not detected
   automatically.
4. Press **Test Device**.
5. Confirm that connection, communication, MAX11300/Pixi, IMU, and USB
   throughput checks pass.

The simple throughput health check runs full-duplex at 10 ksample/s for 30
seconds and requires at least 9.5 ksample/s RX and rendered throughput, with no
steady-state underruns or render-buffer overruns.

For development without hardware, select the mock backend in
`config/config.py`:

```python
HAPTIC_DEVICE_CONFIG["backend"] = "mock"
```

Protocol and firmware details are documented in
[docs/haptic_device_protocol.md](docs/haptic_device_protocol.md).

## Workshop workflow

### Device

Runs the participant-facing device health check. Advanced connection, IMU, and
throughput controls are hidden under **Detailed Info**.

### 1. Recording

Records Pixi and/or IMU signals at a selectable sample rate and duration.
Recordings can also be imported or exported as WAV, CSV, or NPZ.

### 2. Texture Model

Selects a texture representation and compares its reconstructed spectrum with
the original signal.

### 3. Characterization

Plays an excitation through the actuator, records the response, and estimates
its transfer function.

### 4. Compensation

Provides two explicit paths:

- Generate an inverse response from the characterization in step 3.
- Load the current generated filter, a bundled preset, a user-saved filter, or
  another JSON filter.

Both frequency-domain filters and zero-phase `filtfilt` filters are supported.
The screen plots the current signal spectrum before and after compensation.

Bundled filters live in `host/compensation_filters`. User-saved filters are
written outside the installation:

- Windows: `%LOCALAPPDATA%\MakeSense\compensation_filters`
- Linux: `${XDG_DATA_HOME:-$HOME/.local/share}/MakeSense/compensation_filters`

### 5. Rendering

Shows exactly which source, compensation, duration, sample rate, and workshop
output will be played. The workshop UI exposes:

- Output 1 — Haptuator
- Output 2 — LRA

Playback uses a prefilled and continuously replenished hardware buffer to avoid
USB scheduling gaps.

## Configuration

Important settings are in `config/config.py`:

- serial backend, port, baud rate, and timeouts;
- default hardware channels and sample rates;
- recording, modeling, characterization, compensation, and rendering values;
- window dimensions and application title.

## Diagnostics

Useful scripts in `host/scripts` include:

- `render_stream_sweep.py` — sustained host-streamed rendering;
- `haptic_max_throughput.py` — RX, TX, and duplex throughput sweeps;
- `dac_output_test.py` and `dac_sine_test.py` — direct output checks.

## Tests

From `host`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Building executables

Windows and Linux PyInstaller onedir builds are prepared. See
[PACKAGING.md](PACKAGING.md) for dependencies and build commands.

## Theme and licensing

The interface uses the MIT-licensed PyDracula light stylesheet adapted to the
MakeSense palette. The upstream stylesheet and license are retained in
`ui/`.

**Version:** 1.0.0  
**Updated:** June 30, 2026
