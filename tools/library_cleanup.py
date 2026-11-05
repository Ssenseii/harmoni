import os
import subprocess
from constants import VALID_AUDIO_EXTENSIONS
from utils.logger import log_info, log_success, log_error
from utils.system import hidden_subprocess_kwargs

def is_file_corrupted(file_path):
    """
    Uses ffmpeg to check if the file is corrupted.
    Returns True if corrupted or unreadable.
    """
    try:
        cmd = ["ffmpeg", "-v", "error", "-i", file_path, "-f", "null", "-"]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden_subprocess_kwargs())
        return result.returncode != 0
    except Exception:
        return True

def library_cleanup(config):
    """
    Removes broken music files: unreadable, 0 bytes, or corrupted.
    """
    try:
        music_dir = config.get("output_dir", "music")

        if not os.path.exists(music_dir):
            log_error(f"Music folder not found: {music_dir}")
            return

        removed_count = 0
        for root, _, files in os.walk(music_dir):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in VALID_AUDIO_EXTENSIONS:
                    file_path = os.path.join(root, file)
                    if os.path.getsize(file_path) == 0 or is_file_corrupted(file_path):
                        try:
                            os.remove(file_path)
                            removed_count += 1
                            log_info(f"Removed broken file: {file_path}")
                        except Exception as e:
                            log_error(f"Failed to remove {file_path}: {e}")

        log_success(f"Library cleanup complete. Removed {removed_count} broken files.")

    except Exception as e:
        log_error(f"Error during library cleanup: {e}")
