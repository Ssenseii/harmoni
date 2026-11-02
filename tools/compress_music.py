import os
import subprocess
import questionary
from constants import VALID_AUDIO_EXTENSIONS, AUDIO_BITRATE_OPTIONS
from utils.logger import log_info, log_success, log_error
from utils.system import hidden_subprocess_kwargs

def compress_music(config):
    """
    Compresses all audio files in the music folder using ffmpeg with user-chosen bitrate.
    Returns a list of output file paths for compressed files, or None if cancelled.
    """
    try:
        music_dir = config.get("output_dir", "music")

        if not os.path.exists(music_dir):
            log_error(f"Music folder not found: {music_dir}")
            return None

        choices = [f"{br} - {desc}" for br, desc in AUDIO_BITRATE_OPTIONS.items()]
        choices.append("Leave / Cancel")

        bitrate_choice = questionary.select(
            "Select target bitrate:",
            choices=choices
        ).ask()

        if not bitrate_choice or bitrate_choice == "Leave / Cancel":
            log_info("Compression cancelled by user.")
            return None

        target_bitrate = bitrate_choice.split()[0]

        compressed_files = []

        for root, _, files in os.walk(music_dir):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in VALID_AUDIO_EXTENSIONS:
                    input_path = os.path.join(root, file)
                    output_path = os.path.join(root, f"compressed_{file}")

                    cmd = [
                        "ffmpeg", "-y",
                        "-i", input_path,
                        "-b:a", target_bitrate,
                        output_path
                    ]

                    try:
                        subprocess.run(
                            cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=True,
                            **hidden_subprocess_kwargs(),
                        )
                        log_success(f"Compressed: {file}")
                        compressed_files.append(output_path)
                    except Exception as e:
                        log_error(f"Error compressing {file}: {e}")

        return compressed_files

    except Exception as e:
        log_error(f"Failed to compress music: {e}")
        return None
