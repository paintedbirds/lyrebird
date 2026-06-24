#!/bin/zsh
# Creates Lyrebird.app in ~/Applications so it appears in Spotlight.
# Re-run any time you move the whisper-menubar folder.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Lyrebird"
DEST="$HOME/Applications/$APP_NAME.app"

echo "Building $DEST ..."

# Generate the icon if it doesn't exist yet
if [[ ! -f "$DIR/AppIcon.icns" ]]; then
    echo "Generating icon..."
    "$DIR/.venv/bin/python" "$DIR/make_icon.py"
fi

rm -rf "$DEST"
mkdir -p "$DEST/Contents/MacOS"
mkdir -p "$DEST/Contents/Resources/pyhome"

cp "$DIR/AppIcon.icns" "$DEST/Contents/Resources/AppIcon.icns"

# --- Resolve the real venv interpreter + its stdlib home + site-packages ---
# We COPY (not symlink, not a zsh/shebang wrapper) the actual python3.12
# binary into Contents/MacOS/Lyrebird. Two things this buys us:
#  1. No exec() call happens after the process starts (LaunchServices execs
#     this Mach-O binary directly) — avoids the confirmed macOS 26 bug
#     (FB21015611) where NSStatusItem never renders if the bundle's main
#     executable swaps process image via exec() after launch.
#  2. Activity Monitor / the mic permission prompt show "Lyrebird" instead
#     of "Python", because that's now literally the binary's own name.
PY_REAL_BIN="$(readlink -f "$DIR/.venv/bin/python3" 2>/dev/null || python3 -c "import os,sys; print(os.path.realpath('$DIR/.venv/bin/python3'))")"
PY_BASE_PREFIX="$("$DIR/.venv/bin/python3" -c 'import sys; print(sys.base_prefix)')"
PY_SITE_PACKAGES="$("$DIR/.venv/bin/python3" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"

cp "$PY_REAL_BIN" "$DEST/Contents/MacOS/$APP_NAME"
chmod +x "$DEST/Contents/MacOS/$APP_NAME"

# sitecustomize.py runs automatically on interpreter startup (Python's
# `site` module imports it if its directory is on PYTHONPATH) — this is
# what makes the renamed binary actually run app.py instead of dropping
# into a bare REPL. It only fires for THIS bundle: PYTHONPATH below is set
# via LSEnvironment, so it's never on sys.path for normal `python app.py`
# runs from Terminal.
cat > "$DEST/Contents/Resources/pyhome/sitecustomize.py" << PYEOF
import runpy
runpy.run_path("$DIR/app.py", run_name="__main__")
PYEOF

cat > "$DEST/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>              <string>Lyrebird</string>
  <key>CFBundleDisplayName</key>       <string>Lyrebird</string>
  <key>CFBundleIdentifier</key>        <string>com.local.lyrebird</string>
  <key>CFBundleExecutable</key>        <string>Lyrebird</string>
  <key>CFBundleIconFile</key>          <string>AppIcon</string>
  <key>CFBundleVersion</key>           <string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key>       <string>APPL</string>
  <key>LSMinimumSystemVersion</key>    <string>12.0</string>
  <key>NSMicrophoneUsageDescription</key>
    <string>Lyrebird necesita acceso al micrófono para transcribir tu voz.</string>
  <key>LSEnvironment</key>
  <dict>
    <key>PYTHONHOME</key> <string>$PY_BASE_PREFIX</string>
    <key>PYTHONPATH</key> <string>$DEST/Contents/Resources/pyhome:$PY_SITE_PACKAGES:$DIR</string>
  </dict>
</dict>
</plist>
PLIST

/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$DEST" 2>/dev/null || true

echo "Listo. App instalada en $DEST"
echo "Buscá 'Lyrebird' en Spotlight (Cmd+Space) para abrirla."
