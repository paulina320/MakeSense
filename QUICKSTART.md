# MakeSense Quick Start

## Run from source

Open a terminal in the repository root.

### Windows

```powershell
cd host
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

### Linux

```bash
cd host
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python main.py
```

## Connect and test the kit

1. Flash `device/firmware/stm32_haptic_device`.
2. Connect the MakeSense board over USB.
3. Start the application.
4. Open **Device**.
5. If necessary, open **Detailed Info**, select the serial port, and press
   **Connect**.
6. Press **Test Device**.
7. Wait for the 30-second throughput check and confirm that all five checks are
   green.

The application defaults to the serial haptic-device backend. To run without
hardware, change this setting in `host/config/config.py`:

```python
HAPTIC_DEVICE_CONFIG["backend"] = "mock"
```

## Complete the workshop pipeline

### 1. Recording

1. Select the Pixi and/or IMU input.
2. Choose the sample rate and duration.
3. Press **Start Recording**.
4. Inspect the captured waveform.

### 2. Texture Model

1. Select a model.
2. Adjust its parameters.
3. Compare the original and reconstructed spectra.

### 3. Characterization

1. Select the output actuator and response input.
2. Choose the excitation settings.
3. Press **Generate & Run Characterization**.
4. Inspect the measured transfer function.

### 4. Compensation

Choose one path:

- **Generate from Characterization:** compute an inverse filter from step 3.
- **Load an Existing Filter:** use the generated filter, select a preset from
  `host/compensation_filters`, or browse for a JSON filter.

Verify the before/after plot, which shows the compensation applied to the
current recording.

### 5. Rendering

1. Choose **Output 1 — Haptuator** or **Output 2 — LRA**.
2. Press **Prepare Signal**.
3. Confirm the source, compensation, duration, and sample rate shown under
   **What will be played**.
4. Set the volume and optionally enable **Keep playing (loop)**.
5. Press **Play**.

## Build an executable

See [PACKAGING.md](PACKAGING.md) for Windows and Linux PyInstaller builds.
