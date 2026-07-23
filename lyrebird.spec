# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Lyrebird.

Builds a self-contained Lyrebird.app that bundles the Python runtime and every
dependency (MLX/Metal, mlx-whisper, silero-vad, argos-translate, PortAudio,
etc.) so it runs on any Mac without a dev environment.

Whisper model weights are NOT bundled (they are ~0.1-1.5 GB each, MLX format).
They download on first use into ~/.cache/huggingface, exactly as in the dev
build. Same for argos-translate's ES<->EN package (~50-100MB), downloaded on
first use of the pill's translate chip.

NOTE: mlx/mlx-whisper ship compiled Metal shaders/dylibs that PyInstaller may
not discover automatically the way it does pure-Python packages. This is the
biggest unverified packaging risk in the mlx-whisper migration -- build and
run on a clean machine before shipping, not just `python app.py` from source.

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
    "translator",
    "hotkey",
]

# Pull in package data + dynamic libs + submodules for the heavy deps.
for pkg in (
    "mlx",
    "mlx_whisper",
    "argostranslate",
    "silero_vad",
    "sounddevice",
    "scipy",
    "soundfile",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h


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
    version="1.1.0",
    info_plist={
        "CFBundleName": "Lyrebird",
        "CFBundleDisplayName": "Lyrebird",
        "CFBundleShortVersionString": "1.1.0",
        "CFBundleVersion": "1.1.0",
        "LSMinimumSystemVersion": "12.0",
        # Menu-bar accessory app: no Dock icon, no menu bar takeover.
        "LSUIElement": True,
        "NSMicrophoneUsageDescription":
            "Lyrebird necesita acceso al microfono para transcribir tu voz.",
        "NSHighResolutionCapable": True,
    },
)
