# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Lyrebird.

Builds a self-contained Lyrebird.app that bundles the Python runtime and every
dependency (PyTorch, Whisper, silero-vad, PortAudio, etc.) so it runs on any
Mac without a dev environment.

Whisper model weights are NOT bundled (they are ~0.5-1.5 GB each). They download
on first use into ~/.cache/whisper, exactly as in the dev build.

Build:   pyinstaller --noconfirm lyrebird.spec
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [
    ("fonts/Arimo.ttf", "fonts"),
    ("icon-menubar.svg", "."),
]
binaries = []
hiddenimports = [
    # Local sibling modules imported by app.py
    "audio_recorder",
    "store",
    "transcriber",
    "hotkey",
]

# Pull in package data + dynamic libs + submodules for the heavy deps.
for pkg in ("whisper", "silero_vad", "sounddevice", "scipy", "soundfile"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# tiktoken (whisper's tokenizer) ships registry data via plugins.
datas += collect_data_files("tiktoken_ext", include_py_files=True)
hiddenimports += ["tiktoken_ext", "tiktoken_ext.openai_public"]


a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim obvious dead weight to keep the bundle smaller.
        "tkinter",
        "matplotlib",
        "PIL",
        "pytest",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Lyrebird",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app: no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # native arch of the build machine
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Lyrebird",
)

app = BUNDLE(
    coll,
    name="Lyrebird.app",
    icon="AppIcon.icns",
    bundle_identifier="com.paintedbirds.lyrebird",
    version="1.0.1",
    info_plist={
        "CFBundleName": "Lyrebird",
        "CFBundleDisplayName": "Lyrebird",
        "CFBundleShortVersionString": "1.0.1",
        "CFBundleVersion": "1.0.1",
        "LSMinimumSystemVersion": "12.0",
        # Menu-bar accessory app: no Dock icon, no menu bar takeover.
        "LSUIElement": True,
        "NSMicrophoneUsageDescription":
            "Lyrebird necesita acceso al microfono para transcribir tu voz.",
        "NSHighResolutionCapable": True,
    },
)
