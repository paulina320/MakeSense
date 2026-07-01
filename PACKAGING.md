# Building the MakeSense executable

The application uses a PyInstaller **onedir** build. 

## Windows

From the `host` directory:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build_executable.ps1
```

The distributable application is written to:

```text
dist\MakeSense\MakeSense.exe
```

Distribute the complete `dist\MakeSense` directory, not only the executable.

Bundled filters are read from the application resources. Filters saved by a
participant are written to:

```text
%LOCALAPPDATA%\MakeSense\compensation_filters
```

This keeps saving functional even when the application is installed under
`Program Files`.

## Linux

Install the native libraries required by Qt and `sounddevice`. On
Ubuntu/Debian:

```bash
sudo apt-get install libportaudio2 libgl1 libegl1 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xinerama0
```

Create the environment and build from the `host` directory:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m pip install -r requirements-build.txt
bash ./build_executable.sh
```

The Linux distributable is written to:

```text
dist/MakeSense/MakeSense
```

Distribute the complete `dist/MakeSense` directory. PyInstaller does not
cross-compile: run this script on a Linux system compatible with the workshop
machines. For broad compatibility, build on the oldest Linux distribution you
intend to support.

Participant-saved filters are stored in:

```text
${XDG_DATA_HOME:-$HOME/.local/share}/MakeSense/compensation_filters
```
