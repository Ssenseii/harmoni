"""
yt-dlp update checker module.
Checks if a newer version of yt-dlp is available and notifies the user.
"""

import os
import shutil
import subprocess
import json
import urllib.request
import urllib.error
from typing import Optional, Tuple
from utils.logger import log_info, log_warning
from utils.system import hidden_subprocess_kwargs


def get_installed_version(ytdlp_path: Optional[str] = None) -> Optional[str]:
    """
    Get the currently installed version of yt-dlp.

    Args:
        ytdlp_path: Path to a specific yt-dlp binary to check. If not given
            (or it doesn't exist), falls back to whatever "yt-dlp" resolves
            to on PATH.

    Returns:
        Version string (e.g., "2024.01.01") or None if yt-dlp is not installed
    """
    binary = ytdlp_path if ytdlp_path and os.path.isfile(ytdlp_path) else "yt-dlp"
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            **hidden_subprocess_kwargs()
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    except Exception:
        return None


def find_ytdlp(ytdlp_path: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Locate the yt-dlp binary Harmoni would use and read its version.

    @param ytdlp_path: Configured binary to prefer, falling back to PATH when it is not a file.
    """
    if ytdlp_path and os.path.isfile(ytdlp_path):
        found_path = ytdlp_path
    else:
        found_path = shutil.which("yt-dlp")
    if not found_path:
        return None, None
    return found_path, get_installed_version(found_path)


def get_latest_version() -> Optional[str]:
    """
    Fetch the latest version of yt-dlp from PyPI API.

    Returns:
        Latest version string or None if unable to fetch
    """
    try:
        url = "https://pypi.org/pypi/yt-dlp/json"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data["info"]["version"]
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError):
        return None
    except Exception:
        return None


def parse_version(version_str: str) -> Tuple[int, int, int]:
    """
    Parse version string to tuple for comparison.
    Handles versions like "2024.01.01" or "2024.1.1".

    Args:
        version_str: Version string (e.g., "2024.01.01")

    Returns:
        Tuple of (major, minor, patch) as integers
    """
    try:
        parts = version_str.strip().split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except (ValueError, IndexError):
        return (0, 0, 0)


def is_update_available(current: str, latest: str) -> bool:
    """
    Check if an update is available by comparing versions.

    Args:
        current: Currently installed version
        latest: Latest available version

    Returns:
        True if an update is available, False otherwise
    """
    if not current or not latest:
        return False

    current_tuple = parse_version(current)
    latest_tuple = parse_version(latest)

    return latest_tuple > current_tuple


def check_ytdlp_updates(ytdlp_path: Optional[str] = None) -> Optional[dict]:
    """
    Check if yt-dlp has updates available.

    Args:
        ytdlp_path: Path to the yt-dlp binary Harmoni is actually configured
            to use. Passing this avoids reporting a stale/unrelated version
            picked up from PATH.

    Returns:
        Dict with keys:
        - 'update_available': bool
        - 'current_version': str
        - 'latest_version': str
        - 'message': str (human-readable message)
        Or None if unable to check
    """
    current_version = get_installed_version(ytdlp_path)

    if not current_version:
        return {
            'update_available': False,
            'current_version': None,
            'latest_version': None,
            'message': 'Could not determine installed yt-dlp version'
        }

    latest_version = get_latest_version()

    if not latest_version:
        return {
            'update_available': False,
            'current_version': current_version,
            'latest_version': None,
            'message': 'Could not check for yt-dlp updates (network unavailable?)'
        }

    has_update = is_update_available(current_version, latest_version)

    return {
        'update_available': has_update,
        'current_version': current_version,
        'latest_version': latest_version,
        'message': f"yt-dlp update available: {current_version} → {latest_version}" if has_update else f"yt-dlp is up to date ({current_version})"
    }


def notify_update_available(update_info: dict) -> None:
    """
    Display a notification if an update is available.

    Args:
        update_info: Dict returned from check_ytdlp_updates()
    """
    if not update_info:
        return

    if update_info['update_available']:
        message = (
            f"\n{'='*60}\n"
            f"yt-dlp UPDATE AVAILABLE\n"
            f"{'='*60}\n"
            f"Current version: {update_info['current_version']}\n"
            f"Latest version:  {update_info['latest_version']}\n"
            f"\nTo update, run:\n"
            f"  pip install --upgrade yt-dlp\n"
            f"{'='*60}\n"
        )
        log_warning(message.strip())
    else:
        log_info(f"✓ {update_info['message']}")
