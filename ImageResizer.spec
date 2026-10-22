# -*- mode: python ; coding: utf-8 -*-
"""Однофайловая сборка ImageResizer (Windows и macOS).

Использование:
    python -m PyInstaller --clean --noconfirm ImageResizer.spec

Результат: dist/ImageResizer.exe (Windows) или dist/ImageResizer (macOS/Linux).
"""

import os

SRC = os.path.join(SPECPATH, "src")

a = Analysis(
    [os.path.join(SRC, "image_resizer.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Интерфейс консольный: tkinter, numpy и тяжёлые тестовые модули не нужны.
    excludes=["tkinter", "unittest", "pydoc_data", "test", "numpy"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ImageResizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
