# Installation Guide

This guide covers all installation methods for HARMONI.

## Quick Start Options

| Method | Difficulty | Best For |
|--------|------------|----------|
| [Standalone EXE](#standalone-executable) | Easy | Beginners |
| [Python + GUI](#python-installation) | Medium | Most users |
| [Docker](#docker) | Medium | Containers |

---

## Standalone Executable

The easiest way to use HARMONI - no installation required.

### Download

1. Go to [GitHub Releases](https://github.com/Ssenseii/harmoni/releases)
2. Download `HARMONI.exe` (Windows) or `HARMONI-macos-arm64.dmg` (macOS)
3. Double-click to run

### First Run

On first launch, HARMONI will:
- Create a `config.json` file
- Check for FFmpeg and offer to install it

See [Standalone Guide](standalone.md) for detailed instructions.

---

## Python Installation

### Prerequisites

- **Python 3.12+**
- **ffmpeg** - Required for audio extraction/conversion
- Internet connection

### Installing ffmpeg

**Windows:**

Option 1: Let HARMONI install it (GUI Settings > Install FFmpeg)

Option 2: Manual installation
1. Download from https://ffmpeg.org/download.html
2. Extract to a folder (e.g., `C:\ffmpeg`)
3. Add `C:\ffmpeg\bin` to your PATH environment variable

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt install ffmpeg
```

**Fedora:**
```bash
sudo dnf install ffmpeg
```

---

### Quick Install

Use the provided start script for automatic setup:

```bash
./start.sh
```

This script:
- Creates a virtual environment if needed
- Installs all dependencies
- Launches the CLI application

---

### Manual Installation

#### 1. Clone the Repository

```bash
git clone https://github.com/Ssenseii/harmoni.git
cd harmoni
```

#### 2. Create Virtual Environment

```bash
python3 -m venv .venv

# Activate on Linux/macOS
source .venv/bin/activate

# Activate on Windows
.venv\Scripts\activate
```

#### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 4. Run the Application

**GUI (Recommended):**
```bash
python gui_main.py
```

**CLI:**
```bash
python main.py
```

---

## Docker

Run HARMONI in a container without installing Python.

### Using Docker Compose (Recommended)

```bash
# Build the image
docker compose build

# Run interactively
docker compose run --rm --service-ports harmoni
```

### Using Docker Directly

```bash
# Build
docker build -t harmoni .

# Run
docker run -it --rm \
  -v $(pwd)/music:/app/music \
  -v $(pwd)/data:/app/data \
  -p 8888:8888 \
  harmoni
```

See [Docker Guide](docker.md) for detailed instructions.

---

## Verifying Installation

### Check Dependencies

Run the dependency checker:

```bash
python main.py
# Select: Tools Menu > Dependency check
```

Or use the GUI:
- Open Settings tab
- Check "FFmpeg Status"

### Expected Output

```
✓ Python 3.12+
✓ yt-dlp installed
✓ ffmpeg found
✓ PySide6 installed (for GUI)
```

---

## Upgrading

### Upgrade HARMONI

```bash
cd harmoni
git pull
pip install -r requirements.txt
```

### Upgrade yt-dlp

If downloads are failing frequently, update yt-dlp:

```bash
pip install --upgrade yt-dlp
```

---

## Optional: JavaScript Runtime

For improved YouTube extraction reliability, install a JavaScript runtime:

- **Node.js** (recommended): https://nodejs.org
- **Deno**: https://deno.land
- **QuickJS**: https://bellard.org/quickjs/

This helps yt-dlp handle certain YouTube pages that require JavaScript execution.

---

## Troubleshooting

### "Python not found"

Ensure Python is in your PATH:
```bash
python --version
# or
python3 --version
```

### "pip not found"

Use Python's pip module:
```bash
python -m pip install -r requirements.txt
```

### "ffmpeg not found"

Ensure ffmpeg is in your PATH:
```bash
ffmpeg -version
```

If not found, reinstall ffmpeg and ensure it's added to PATH.

### Permission denied (Linux/macOS)

```bash
chmod +x start.sh
./start.sh
```

### GUI not launching

Ensure PySide6 is installed:
```bash
pip install PySide6
```

---

## Next Steps

- [GUI Guide](gui.md) - Using the desktop application
- [CLI Guide](cli.md) - Command-line interface
- [Spotify Setup](spotify-setup.md) - Connect your Spotify account
- [Configuration](configuration.md) - Customize settings
