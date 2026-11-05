#!/usr/bin/env bash
set -euo pipefail

echo "=== HARMONI macOS Build ==="

# Check we're on macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo "Error: This script must be run on macOS"
    exit 1
fi

ARCH="$(uname -m)"
echo "Architecture: $ARCH"

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install Python 3.12+ first."
    exit 1
fi

# Install Python dependencies
echo "=== Installing Python dependencies ==="
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

# Install ffmpeg if not present
if ! command -v brew &>/dev/null; then
    echo "Error: Homebrew not found. Install from https://brew.sh"
    exit 1
fi

if ! command -v ffmpeg &>/dev/null; then
    echo "=== Installing FFmpeg via Homebrew ==="
    brew install ffmpeg
fi

# Copy binaries for bundling
echo "=== Bundling binaries ==="
mkdir -p bin
cp "$(which ffmpeg)" bin/ffmpeg
cp "$(which ffprobe)" bin/ffprobe

# Download standalone yt-dlp binary (Homebrew version is a Python wrapper that won't work bundled)
echo "=== Downloading standalone yt-dlp ==="
curl -fL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos -o bin/yt-dlp
chmod +x bin/yt-dlp

# Convert icon to icns
echo "=== Converting icon ==="
mkdir -p icon.iconset
sips -z 16 16     gui/resources/icons/app/app_icon.png --out icon.iconset/icon_16x16.png
sips -z 32 32     gui/resources/icons/app/app_icon.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     gui/resources/icons/app/app_icon.png --out icon.iconset/icon_32x32.png
sips -z 64 64     gui/resources/icons/app/app_icon.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   gui/resources/icons/app/app_icon.png --out icon.iconset/icon_128x128.png
sips -z 256 256   gui/resources/icons/app/app_icon.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   gui/resources/icons/app/app_icon.png --out icon.iconset/icon_256x256.png
sips -z 512 512   gui/resources/icons/app/app_icon.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   gui/resources/icons/app/app_icon.png --out icon.iconset/icon_512x512.png
sips -z 1024 1024 gui/resources/icons/app/app_icon.png --out icon.iconset/icon_512x512@2x.png
iconutil -c icns icon.iconset -o HARMONI.icns

# Build with PyInstaller
# Do not add --strip here: bin/yt-dlp is itself a PyInstaller onefile binary whose
# Python archive is appended to the executable, and strip discards that archive,
# leaving a bootloader stub that exits 255 on every run.
echo "=== Building with PyInstaller ==="
pyinstaller \
    --name "HARMONI" \
    --windowed \
    --onedir \
    --icon HARMONI.icns \
    --add-data "gui/resources/icons:gui/resources/icons" \
    --add-binary "bin/ffmpeg:bin" \
    --add-binary "bin/ffprobe:bin" \
    --add-binary "bin/yt-dlp:bin" \
    --add-data "config.json.example:." \
    gui_main.py

# Create DMG
echo "=== Creating DMG ==="
rm -rf dmg_contents
mkdir -p dmg_contents
if [ -d "dist/HARMONI.app" ]; then
    cp -r dist/HARMONI.app dmg_contents/
else
    cp -r dist/HARMONI dmg_contents/
fi

# Add Applications symlink so users can drag to install
ln -s /Applications dmg_contents/Applications

DMG_NAME="HARMONI-macos-${ARCH}.dmg"
hdiutil create -volname "HARMONI" -srcfolder dmg_contents -ov -format UDZO "$DMG_NAME"

# Cleanup build artifacts
rm -rf build icon.iconset dmg_contents HARMONI.icns bin

echo ""
echo "=== Build complete ==="
echo "Output: $DMG_NAME"
echo ""
echo "To install: open the DMG and drag HARMONI to Applications."
echo "On first launch, right-click > Open to bypass Gatekeeper."
