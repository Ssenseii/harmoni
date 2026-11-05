"""Background workers that check the yt-dlp install and look for a newer yt-dlp release."""

from PySide6.QtCore import QThread, Signal

from tools.ytdlp_update_checker import check_ytdlp_updates, find_ytdlp


class YtdlpUpdateCheckWorker(QThread):
    """Runs the yt-dlp version and PyPI check off the UI thread."""

    update_available = Signal(dict)

    def __init__(self, ytdlp_path: str = None, parent=None):
        """Create the worker.

        @param ytdlp_path: Configured yt-dlp binary to check, or None to use PATH.
        """
        super().__init__(parent)
        self.ytdlp_path = ytdlp_path

    def run(self):
        """Check for a yt-dlp update and emit update_available when one exists."""
        info = check_ytdlp_updates(self.ytdlp_path)
        if info and info.get("update_available"):
            self.update_available.emit(info)


class YtdlpStatusWorker(QThread):
    """Finds the yt-dlp binary and its version off the UI thread."""

    status_ready = Signal(str, str)

    def __init__(self, ytdlp_path: str = None, parent=None):
        """Create the worker.

        @param ytdlp_path: Configured yt-dlp binary to check first, or None to use PATH.
        """
        super().__init__(parent)
        self.ytdlp_path = ytdlp_path

    def run(self):
        """Emit status_ready with the found path and version, empty strings when unknown."""
        found_path, version = find_ytdlp(self.ytdlp_path)
        self.status_ready.emit(found_path or "", version or "")
