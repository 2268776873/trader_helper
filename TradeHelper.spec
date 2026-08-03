# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

# Refuse to silently produce a GUI executable without Tcl/Tk. PyInstaller's
# tkinter hook skips the whole module when its isolated probe fails (e.g. under
# filesystem virtualization), yielding an exe that crashes on startup with
# "No module named 'tkinter'". Fail loudly instead.
from PyInstaller.utils.hooks.tcl_tk import tcltk_info

if not tcltk_info.available:
    raise SystemExit(
        "FATAL: PyInstaller cannot use Tcl/Tk in this build environment.\n"
        "Rebuild from a normal (non-sandboxed) shell so tkinter.Tcl() can "
        "locate init.tcl, or fix the Python/Tcl installation."
    )

root = Path(SPECPATH)

a = Analysis(
    [str(root / "src" / "trade_helper" / "ui" / "app.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[
        (str(root / "config"), "config"),
        (
            str(root / "outputs" / "account_template" / "trade_helper_account_template.xlsx"),
            "templates",
        ),
    ],
    hiddenimports=["tkinter", "openpyxl"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TradeHelper",
    version=str(root / "installer" / "windows_version_info.txt"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
)
