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
mkdir -p "$DEST/Contents/Resources"

cp "$DIR/AppIcon.icns" "$DEST/Contents/Resources/AppIcon.icns"

cat > "$DEST/Contents/MacOS/$APP_NAME" << LAUNCHER
#!$DIR/.venv/bin/python3
# NOTE: this file's shebang line IS the interpreter — there is no zsh
# wrapper and no runtime exec() call. macOS 26 has a confirmed bug
# (FB21015611) where, if a bundle's main executable is a script that
# itself calls exec() to swap to a different process image *after*
# starting, the NSStatusItem never renders when launched via
# Finder/LaunchServices. A shebang is resolved by the kernel in a single
# execve before any of our code runs, so it does not trigger that bug —
# this is what lets the menu bar icon work from a normal Finder/Spotlight
# launch.
import sys, runpy
sys.path.insert(0, "$DIR")
runpy.run_path("$DIR/app.py", run_name="__main__")
LAUNCHER
chmod +x "$DEST/Contents/MacOS/$APP_NAME"

cat > "$DEST/Contents/Info.plist" << 'PLIST'
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
</dict>
</plist>
PLIST

/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$DEST" 2>/dev/null || true

echo "Listo. App instalada en $DEST"
echo "Buscá 'Lyrebird' en Spotlight (Cmd+Space) para abrirla."
