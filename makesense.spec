# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build for the MakeSense workshop application."""

from pathlib import Path
from PyInstaller.compat import is_win
from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "ui" / "icons"), "ui/icons"),
    (str(ROOT / "ui" / "py_dracula_light.qss"), "ui"),
    (str(ROOT / "ui" / "PYDRACULA_LICENSE"), "ui"),
    (str(ROOT / "compensation_filters"), "compensation_filters"),
]

hiddenimports = (
    collect_submodules("serial.tools")
    + collect_submodules("qrcode")
    + [
        "scipy.signal",
        "scipy.fftpack",
        "sounddevice",
    ]
)

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "IPython", "jupyter", "notebook"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MakeSense",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=str(ROOT / "ui" / "icons" / "makesense.ico") if is_win else None,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MakeSense",
)
