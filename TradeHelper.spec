# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

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
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
)
