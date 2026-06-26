#!/bin/zsh
# Creates Lyrebird.app in ~/Applications so it appears in Spotlight.
# Re-run any time you move the lyrebird folder.
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

# --- Resolve the FRAMEWORK python + its stdlib home + site-packages ---
# We COPY the *framework* python binary into Contents/MacOS/Lyrebird.
# CRITICAL: it must be the framework python (Resources/Python.app/.../Python),
# NOT bin/python3.12. On macOS, bin/python3.12 re-exec()s itself to the
# framework python at startup; that post-launch exec() triggers the confirmed
# macOS 26 bug (FB21015611) where the NSStatusItem never renders when launched
# via Finder/Spotlight/login. The framework python does NOT re-exec, so the
# menu bar icon renders. Bonus: Activity Monitor / the mic prompt show
# "Lyrebird".
PY_BASE_PREFIX="$("$DIR/.venv/bin/python3" -c 'import sys; print(sys.base_prefix)')"
PY_SITE_PACKAGES="$("$DIR/.venv/bin/python3" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
PY_FW_BIN="$PY_BASE_PREFIX/Resources/Python.app/Contents/MacOS/Python"

cp "$PY_FW_BIN" "$DEST/Contents/MacOS/$APP_NAME"
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
