"""Download worker thread for GUI."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from PySide6.QtCore import QThread, Signal

from downloader.ytdlp_command import run_download
from gui.workers.download_queue import DownloadQueue, DownloadStatus, QueueItem
from utils import log_error, log_info, log_warning
from utils.track_checker import find_existing_track

DEFAULT_CONCURRENT_DOWNLOADS = 1
MAX_CONCURRENT_DOWNLOADS = 8


class DownloadWorker(QThread):
    """
    Worker thread that processes downloads from the queue, running up to concurrent_downloads tracks at once.

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
        self._processes = set()
        self._lock = threading.Lock()
        self._success_count = 0
        self._fail_count = 0

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

        self._success_count = 0
        self._fail_count = 0
        self.queue.set_running(True)

        slots = self._concurrency()
        with ThreadPoolExecutor(max_workers=slots, thread_name_prefix="download") as pool:
            futures = [pool.submit(self._run_slot) for _ in range(slots)]
        for future in futures:
            if future.exception() is not None:
                log_error(f"Download slot stopped: {future.exception()}")

        self.queue.set_running(False)
        self.queue.mark_queue_completed()
        self.all_completed.emit(self._success_count, self._fail_count)

    def _concurrency(self) -> int:
        """Return how many downloads run at once, from concurrent_downloads clamped to 1-8."""
        try:
            value = int(self.config.get("concurrent_downloads", DEFAULT_CONCURRENT_DOWNLOADS))
        except (TypeError, ValueError):
            value = DEFAULT_CONCURRENT_DOWNLOADS
        return max(1, min(MAX_CONCURRENT_DOWNLOADS, value))

    def _claim_next(self) -> Optional[QueueItem]:
        """Mark the next pending item as downloading and return it, so no two slots take the same track."""
        with self._lock:
            item = self.queue.get_next_pending()
            if item:
                self.queue.update_item_status(item.id, DownloadStatus.DOWNLOADING, progress=0)
            return item

    def _run_slot(self):
        """Download pending items one after another until the queue is empty or cancelled."""
        while not self._cancelled:
            if self._paused:
                self.msleep(100)
                continue

            item = self._claim_next()
            if not item:
                break
            self.track_started.emit(item.artist, item.track)

            try:
                success, file_path, error = self._download_single(item)
            except Exception as e:
                success, file_path, error = False, None, str(e)

            if success:
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.COMPLETED,
                    progress=100,
                    file_path=file_path
                )
                self.track_completed.emit(item.id, True, file_path or "")
                with self._lock:
                    self._success_count += 1
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
                with self._lock:
                    self._fail_count += 1

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

        # Skip tracks that are already on disk
        existing = find_existing_track(output_dir, track_data)
        if existing:
            log_info(f"Already downloaded, skipping: {item.artist} - {item.track}")
            return True, existing, None

        started = []

        def on_popen(process):
            started.append(process)
            self._add_process(process)

        try:
            result = run_download(
                track_data,
                output_dir,
                audio_format,
                self.config,
                popen_hook=on_popen,
                cancel_check=lambda: self._cancelled,
            )
        except Exception as e:
            return False, None, str(e)
        finally:
            with self._lock:
                self._processes.difference_update(started)

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

    def _add_process(self, process):
        """Remember a running yt-dlp process so cancel() can stop it, stopping it at once if cancel() already ran.

        @param process: The Popen started by run_download.
        """
        with self._lock:
            self._processes.add(process)
        if self._cancelled:
            self._terminate(process)

    @staticmethod
    def _terminate(process):
        """Terminate a yt-dlp process that is still running.

        @param process: Popen to stop.
        """
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

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
        """Cancel the downloads and terminate every running yt-dlp."""
        self._cancelled = True
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            self._terminate(process)

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
