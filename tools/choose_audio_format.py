import questionary
from config import save_config
from constants import VALID_AUDIO_EXTENSIONS
from utils.logger import log_success, log_error

def choose_audio_format(config):
    """
    Lets user choose audio format, showing the active one first.
    """
    try:
        current_format = config.get("audio_format", "mp3")
        formats = list(VALID_AUDIO_EXTENSIONS)
        formats_display = [f"{fmt} {'(active)' if fmt.strip('.') == current_format else ''}" for fmt in formats]

        choice = questionary.select(
            "Select audio format:",
            choices=formats_display
        ).ask()

        if not choice:
            return

        new_format = choice.split()[0].strip(".")
        config["audio_format"] = new_format

        save_config(config)

        log_success(f"Audio format updated to: {new_format}")

    except Exception as e:
        log_error(f"Failed to update audio format: {e}")
