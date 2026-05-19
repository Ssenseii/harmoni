"""Download worker thread for GUI."""

import os
import subprocess
from typing import Optional

from PySide6.QtCore import QThread, Signal

from gui.workers.download_queue import DownloadQueue, DownloadStatus, QueueItem


class DownloadWorker(QThread):
    """
    Worker thread that processes downloads from the queue.

    Signals:
        track_started: Emitted when a track download begins (artist, track)
        track_progress: Emitted during download (item_id, progress 0-100)
        track_completed: Emitted when a track finishes (item_id, success, file_path)
        track_failed: Emitted when a track fails (item_id, error_message)
        all_completed: Emitted when all downloads finish (success_count, fail_count)
    """

    track_started = Signal(str, str)  # artist, track
    track_progress = Signal(str, int)  # item_id, progress
    track_completed = Signal(str, bool, str)  # item_id, success, file_path
    track_failed = Signal(str, str)  # item_id, error_message
    all_completed = Signal(int, int)  # success_count, fail_count

    def __init__(self, queue: DownloadQueue, config: dict, parent=None):
        super().__init__(parent)
        self.queue = queue
        self.config = config
        self._cancelled = False
        self._paused = False

    def run(self):
        """Process all pending downloads in the queue."""
        from utils.ffmpeg import configure_ffmpeg_path

        # Configure FFmpeg path
        try:
            configure_ffmpeg_path()
        except FileNotFoundError as e:
            # FFmpeg not found - fail all downloads
            for item in self.queue.get_pending_items():
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.FAILED,
                    error_message=str(e)
                )
                self.track_failed.emit(item.id, str(e))
            return

        success_count = 0
        fail_count = 0

        self.queue.set_running(True)

        while not self._cancelled:
            # Check for pause
            if self._paused:
                self.msleep(100)
                continue

            # Get next pending item
            item = self.queue.get_next_pending()
            if not item:
                break

            # Mark as downloading
            self.queue.update_item_status(item.id, DownloadStatus.DOWNLOADING, progress=0)
            self.track_started.emit(item.artist, item.track)

            # Download the track
            success, file_path, error = self._download_single(item)

            if self._cancelled:
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.CANCELLED,
                    error_message="Cancelled by user"
                )
                break

            if success:
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.COMPLETED,
                    progress=100,
                    file_path=file_path
                )
                self.track_completed.emit(item.id, True, file_path or "")
                success_count += 1
            else:
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.FAILED,
                    error_message=error
                )
                self.track_failed.emit(item.id, error or "Unknown error")
                fail_count += 1

        self.queue.set_running(False)
        self.queue.mark_queue_completed()
        self.all_completed.emit(success_count, fail_count)

    def _download_single(self, item: QueueItem) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Download a single track.

        Returns:
            Tuple of (success, file_path, error_message)
        """
        output_dir = self.config.get("output_dir", "music")
        audio_format = self.config.get("audio_format", "mp3")

        # Handle relative paths - make absolute from project root
        if not os.path.isabs(output_dir):
            # Get the project root (where gui_main.py is)
            import sys
            if getattr(sys, 'frozen', False):
                # Running as compiled executable
                base_dir = os.path.dirname(sys.executable)
            else:
                # Running as script
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(base_dir, output_dir)

        # Create per-playlist subfolder if track has a playlist name
        if item.playlist:
            sanitized = item.playlist.replace("/", "-").replace("\\", "-").strip()
            if sanitized:
                output_dir = os.path.join(output_dir, sanitized)

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        query = f"{item.artist} - {item.track}"
        filename = query.replace("/", "-").replace("\\", "-")

        cmd = [
            "yt-dlp",
            f"ytsearch1:{query}",
            "-x",
            "--audio-format", audio_format,
            "-o", os.path.join(output_dir, f"{filename}.%(ext)s"),
            "--no-playlist",
            "--quiet",
            "--progress"
        ]

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            # Wait for completion
            stdout, stderr = process.communicate()

            if process.returncode == 0:
                # Try to find the downloaded file
                expected_path = os.path.join(output_dir, f"{filename}.{audio_format}")
                if os.path.exists(expected_path):
                    # Embed metadata if enabled
                    self._embed_metadata(expected_path, item)
                    return True, expected_path, None

                # Try to find with any extension
                for ext in [audio_format, "mp3", "m4a", "opus", "webm"]:
                    check_path = os.path.join(output_dir, f"{filename}.{ext}")
                    if os.path.exists(check_path):
                        self._embed_metadata(check_path, item)
                        return True, check_path, None

                return True, None, None
            else:
                error_msg = stderr.strip() if stderr else "Download failed"
                return False, None, error_msg

        except FileNotFoundError:
            return False, None, "yt-dlp not found. Please install yt-dlp."
        except Exception as e:
            return False, None, str(e)

    def _embed_metadata(self, file_path: str, item: QueueItem):
        """Embed metadata into the downloaded file."""
        if not self.config.get("enable_metadata_embedding", True):
            return

        try:
            from downloader.metadata import embed_track_metadata

            track_data = {
                "artist": item.artist,
                "track": item.track,
                "album": item.album or "",
                "album_art_url": item.album_art_url or "",
            }
            template = self.config.get("metadata_template", "comprehensive")
            enable_musicbrainz = self.config.get("enable_musicbrainz_lookup", True)

            embed_track_metadata(
                file_path,
                track_data,
                template=template,
                allow_musicbrainz=enable_musicbrainz,
                config=self.config,
            )
        except ImportError:
            pass
        except Exception:
            pass

    def cancel(self):
        """Cancel the download process."""
        self._cancelled = True

    def pause(self):
        """Pause the download process."""
        self._paused = True
        self.queue.set_paused(True)

    def resume(self):
        """Resume the download process."""
        self._paused = False
        self.queue.set_paused(False)

    @property
    def is_paused(self) -> bool:
        """Check if downloads are paused."""
        return self._paused
