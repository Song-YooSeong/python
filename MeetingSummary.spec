# -*- mode: python ; coding: utf-8 -*-
import sysconfig

datas = []
binaries = []
hiddenimports = ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "docx"]

datas.append((f"{sysconfig.get_path('stdlib')}\\platform.py", "Lib"))

a = Analysis(
    ["src\\MeetingSummary.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pandas", "scipy", "matplotlib", "PIL", "tkinter", "pytest",
        "fastapi", "uvicorn", "jinja2", "openpyxl", "torch", "torchaudio",
        "torchvision", "tensorflow", "sklearn", "numba",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MeetingSummary",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
