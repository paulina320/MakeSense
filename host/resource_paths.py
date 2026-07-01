"""Paths that work both from source and from a PyInstaller bundle."""

from pathlib import Path
import os
import sys


def bundled_path(*parts: str) -> Path:
    """Resolve a read-only application resource."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def user_data_path(*parts: str, create: bool = False) -> Path:
    """Resolve writable per-user application data."""
    if sys.platform.startswith("win"):
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        base = root / "MakeSense"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "MakeSense"
    path = base.joinpath(*parts)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path
