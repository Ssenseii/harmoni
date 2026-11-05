"""Download worker thread for GUI."""

import os
from typing import Optional

from PySide6.QtCore import QThread, Signal

from downloader.ytdlp_command import run_download
from gui.workers.download_queue import DownloadQueue, DownloadStatus, QueueItem
from utils import log_error, log_warning


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
        self._process = None

    def run(self):
        """Process all pending downloads in the queue."""
        from utils.ffmpeg import configure_ffmpeg_path

        # Configure FFmpeg path
        try:
            configure_ffmpeg_path()
        except FileNotFoundError as e:
            # FFmpeg not found - fail all downloads
            pending = self.queue.get_pending_items()
            for item in pending:
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.FAILED,
                    error_message=str(e)
                )
                self.track_failed.emit(item.id, str(e))
            self.all_completed.emit(0, len(pending))
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

            if success:
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.COMPLETED,
                    progress=100,
                    file_path=file_path
                )
                self.track_completed.emit(item.id, True, file_path or "")
                success_count += 1
            elif self._cancelled:
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.CANCELLED,
                    error_message="Cancelled by user"
                )
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

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        track_data = self._track_data(item)
        try:
            result = run_download(
                track_data,
                output_dir,
                audio_format,
                self.config,
                popen_hook=self._set_process,
                cancel_check=lambda: self._cancelled,
            )
        except Exception as e:
            return False, None, str(e)
        finally:
            self._process = None

        if result.success and result.path:
            self._embed_metadata(result.path, item)
        return result.success, result.path, result.error

    @staticmethod
    def _track_data(item: QueueItem) -> dict:
        """Return the item's source track dict with its artist and track names applied.

        @param item: Queue item being downloaded.
        """
        track_data = dict(item.track_data or {})
        track_data["artist"] = item.artist
        track_data["track"] = item.track
        return track_data

    def _set_process(self, process):
        """Remember the running yt-dlp process so cancel() can stop it.

        @param process: The Popen started by run_download.
        """
        self._process = process

    def _embed_metadata(self, file_path: str, item: QueueItem):
        """Embed metadata from the item's full track dict into the downloaded file.

        @param file_path: Path of the downloaded audio file.
        @param item: Queue item whose track_data supplies the tags.
        """
        if not self.config.get("enable_metadata_embedding", True):
            return

        try:
            from downloader.metadata import embed_track_metadata

            template = self.config.get("metadata_template", "basic")
            enable_musicbrainz = self.config.get("enable_musicbrainz_lookup", True)

            embed_track_metadata(
                file_path,
                self._track_data(item),
                template=template,
                allow_musicbrainz=enable_musicbrainz,
                config=self.config,
            )
        except ImportError:
            log_warning("Metadata embedding module not available, skipping metadata embedding")
        except Exception as e:
            log_error(f"Metadata embedding failed for {file_path}: {e}")

    def cancel(self):
        """Cancel the download process and terminate a running yt-dlp."""
        self._cancelled = True
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

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
