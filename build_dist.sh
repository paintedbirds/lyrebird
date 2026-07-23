#!/bin/zsh
# Build a distributable Lyrebird.app + Lyrebird.dmg with PyInstaller.
#
# Unlike build_app.sh (which makes a dev-only launcher that points back to this
# source folder), this produces a SELF-CONTAINED app that runs on any Mac.
#
# Usage:  ./build_dist.sh
#
# Output: dist/Lyrebird.app   and   dist/Lyrebird.dmg
#
# Notes:
#  - Whisper model weights are downloaded on first use (~0.5 GB), not bundled.
#  - This produces an UNSIGNED, ad-hoc-signed app. See SIGNING below for the
#    steps to notarize once you have an Apple Developer account.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PY="$DIR/.venv/bin/python"
APP="dist/Lyrebird.app"
DMG="dist/Lyrebird.dmg"
VOL="Lyrebird"

echo "==> Ensuring icon exists"
if [[ ! -f "$DIR/AppIcon.icns" ]]; then
    "$PY" "$DIR/make_icon.py"
fi

echo "==> Installing PyInstaller into the venv (if missing)"
"$PY" -m pip install --quiet --upgrade pyinstaller

echo "==> Cleaning previous build"
rm -rf build dist

echo "==> Building app bundle (this takes a few minutes; mlx/mlx-whisper are large)"
"$PY" -m PyInstaller --noconfirm lyrebird.spec

if [[ ! -d "$APP" ]]; then
    echo "ERROR: build did not produce $APP" >&2
    exit 1
fi

echo "==> Ad-hoc signing the bundle"
# Ad-hoc (-) signing lets the app run locally and after a manual Gatekeeper
# override. Replace with a Developer ID identity to notarize (see SIGNING).
codesign --force --deep --sign - "$APP"

echo "==> Creating DMG"
rm -f "$DMG"
# Stage a folder with the app + an Applications symlink for drag-to-install.
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "$VOL" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

echo ""
echo "Done."
echo "  App: $DIR/$APP"
echo "  DMG: $DIR/$DMG  ($(du -sh "$DMG" | cut -f1))"
echo ""
echo "Test it:   open \"$APP\"   (look for the Lyrebird icon in the menu bar)"
echo ""
cat <<'SIGNING'
--------------------------------------------------------------------------
SIGNING / NOTARIZATION (needed before public distribution)
--------------------------------------------------------------------------
The DMG above is ad-hoc signed. Downloaded by others, macOS Gatekeeper will
say "Lyrebird is damaged / cannot be opened" because it is not notarized.

To distribute publicly you need an Apple Developer account ($99/yr), then:

  1. Sign with your Developer ID:
     codesign --force --deep --options runtime \
       --sign "Developer ID Application: YOUR NAME (TEAMID)" dist/Lyrebird.app

  2. Notarize (submit to Apple, wait for approval):
     xcrun notarytool submit dist/Lyrebird.dmg \
       --apple-id you@example.com --team-id TEAMID \
       --password APP_SPECIFIC_PASSWORD --wait

  3. Staple the ticket so it works offline:
     xcrun stapler staple dist/Lyrebird.dmg

Until then, testers can run it via: right-click the app > Open > Open,
or:  xattr -dr com.apple.quarantine /Applications/Lyrebird.app
--------------------------------------------------------------------------
SIGNING
