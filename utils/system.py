import subprocess
import sys

import psutil
from utils.logger import log_info, log_warning

def system_check():
    try:
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        cpu_percent = psutil.cpu_percent(interval=1)

        log_info(f"CPU Usage: {cpu_percent}%")
        log_info(f"RAM Available: {ram.available // (1024*1024)} MB")
        log_info(f"Disk Free: {disk.free // (1024*1024*1024)} GB")

        if ram.available < 200*1024*1024:
            log_warning("Low RAM available. Downloads might fail.")
        if disk.free < 1*1024*1024*1024:
            log_warning("Low disk space available.")
    except Exception as e:
        log_warning(f"System check failed: {e}")


def hidden_subprocess_kwargs() -> dict:
    """Return subprocess keyword arguments that stop a console window from opening on Windows."""
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}
