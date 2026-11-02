import os
import sys


def _app_dir() -> str:
    """Return the exe folder when frozen, otherwise the folder holding this file."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _app_dir()

PYTHON_DEPENDENCIES = [
    "psutil",
    "colorama",
    "mutagen",
    "schedule",
    "questionary",
]

SYSTEM_DEPENDENCIES = [
    "ffmpeg",
]

# Audio Related

VALID_AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"}

AUDIO_BITRATE_OPTIONS = {
    "64k": "Very low quality (speech/podcasts)",
    "96k": "Low quality (voice focus)",
    "128k": "Medium quality (most music)",
    "192k": "Good quality (balanced size)",
    "256k": "High quality",
    "320k": "Best quality (larger file size)"
}


# Files

FAILED_FILE = os.path.join(APP_DIR, "data", "failed_downloads.json")
PROGRESS_FILE = os.path.join(APP_DIR, "data", "download_progress.json")
LOG_FILE = os.path.join(APP_DIR, "app.log")
