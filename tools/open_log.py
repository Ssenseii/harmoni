import subprocess
import platform
import os
from constants import LOG_FILE
from utils.system import hidden_subprocess_kwargs

def open_log():
    """
    Opens the app.log file
    """
    if not os.path.exists(LOG_FILE):
        print(f"Log file '{LOG_FILE}' does not exist.")
        return

    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(LOG_FILE)
        elif system == "Darwin":  # macOS
            subprocess.run(["open", LOG_FILE], **hidden_subprocess_kwargs())
        else:  # Linux and others
            subprocess.run(["xdg-open", LOG_FILE], **hidden_subprocess_kwargs())
    except Exception as e:
        print(f"Failed to open log file: {e}")