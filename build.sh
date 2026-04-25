#!/usr/bin/env bash
# Build a standalone Murmur.app bundle for macOS.
#
# Output: dist/Murmur.app  (drag-into-Applications style bundle)
#
# Usage:
#   ./build.sh              # full build
#   ./build.sh --clean      # remove dist/ and build/ first
#
# Requires: macOS, the .venv created by start.sh, Python 3.11.
set -euo pipefail

cd "$(dirname "$0")"

CLEAN=0
for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN=1 ;;
        -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown flag: $arg" >&2; exit 1 ;;
    esac
done

if [[ "$(uname)" != "Darwin" ]]; then
    echo "build.sh currently supports macOS only. Windows packaging is on the roadmap (v1.0)." >&2
    exit 2
fi

# 1. Make sure the venv exists, with packaging extras installed.
if [[ ! -x .venv/bin/python ]]; then
    echo "[build.sh] no .venv found — run ./start.sh --setup-only first." >&2
    exit 3
fi

echo "[build.sh] installing build extras into .venv..."
uv pip install --python .venv/bin/python -e ".[gui,build]"

# 2. Generate the icon if missing.
if [[ ! -f assets/icon.png ]]; then
    echo "[build.sh] generating assets/icon.png"
    .venv/bin/python tools/make_icon.py
fi
if [[ ! -f assets/icon.icns ]]; then
    echo "[build.sh] generating assets/icon.icns"
    bash tools/make_icns.sh assets/icon.png assets/icon.icns
fi

# 3. Clean if asked.
if [[ $CLEAN -eq 1 ]]; then
    echo "[build.sh] cleaning dist/ and build/"
    rm -rf dist build
fi

# 4. Run PyInstaller via the venv's pyinstaller.
#
# We point PyInstaller at tools/pyi_launcher.py rather than
# src/murmur/__main__.py — otherwise PyInstaller treats __main__.py as a
# top-level script and the package's relative imports blow up at runtime
# with "attempted relative import with no known parent package". The
# launcher does the right thing: import murmur.__main__:main and dispatch.
echo "[build.sh] running PyInstaller..."
.venv/bin/pyinstaller \
    --noconfirm \
    --windowed \
    --name "Murmur" \
    --icon "assets/icon.icns" \
    --osx-bundle-identifier "com.bonian.murmur" \
    --paths "src" \
    --collect-submodules "murmur" \
    --collect-submodules "faster_whisper" \
    --collect-data "faster_whisper" \
    --hidden-import "pynput.keyboard._darwin" \
    --hidden-import "pynput.mouse._darwin" \
    tools/pyi_launcher.py

APP="dist/Murmur.app"
PLIST="$APP/Contents/Info.plist"

if [[ ! -d "$APP" ]]; then
    echo "[build.sh] expected $APP, not found — PyInstaller didn't produce a bundle." >&2
    echo "[build.sh] dist/ contents:" >&2
    ls -la dist/ >&2 || true
    exit 4
fi

# 5. Patch Info.plist:
#    - LSUIElement=true so the app lives only in the menu bar (no Dock icon)
#    - NSMicrophoneUsageDescription so the mic permission prompt is human-readable
#    - NSAppleEventsUsageDescription for future auto-paste support
echo "[build.sh] patching Info.plist..."
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string 'Murmur needs microphone access to transcribe what you say into text.'" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :NSMicrophoneUsageDescription 'Murmur needs microphone access to transcribe what you say into text.'" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :NSAppleEventsUsageDescription string 'Murmur uses Apple Events to paste transcribed text into the focused app.'" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :NSAppleEventsUsageDescription 'Murmur uses Apple Events to paste transcribed text into the focused app.'" "$PLIST"

# 6. Ad-hoc sign so Gatekeeper accepts it on the dev machine. Real notarization
#    is a v1.0 task.
echo "[build.sh] ad-hoc signing..."
codesign --force --deep --sign - "$APP" >/dev/null

echo
echo "[build.sh] build complete."
echo "  open dist/Murmur.app"
echo "  or drag dist/Murmur.app into /Applications"
