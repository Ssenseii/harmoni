"""Download worker thread for GUI with concurrent thread pool."""

import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from PySide6.QtCore import QThread, Signal

from gui.workers.download_queue import DownloadQueue, DownloadStatus, QueueItem


class DownloadWorker(QThread):
    """
    Worker thread that processes downloads from the queue using a thread pool.

    Downloads run concurrently up to max_concurrent_downloads threads.
    The main QThread loop submits tasks to the pool and collects results.

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
        self._lock = threading.Lock()

    @property
    def max_workers(self) -> int:
        """Get the max concurrent downloads from config."""
        return max(1, min(8, self.config.get("max_concurrent_downloads", 3)))

    def run(self):
        """Process all pending downloads in the queue using a thread pool."""
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

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}

            while not self._cancelled:
                # Check for pause
                if self._paused:
                    self.msleep(100)
                    continue

                # Collect completed futures
                done_ids = []
                for future_id, future in futures.items():
                    if future.done():
                        done_ids.append(future_id)

                for future_id in done_ids:
                    future = futures.pop(future_id)
                    try:
                        item, success, file_path, error = future.result()
                    except Exception as e:
                        # Unexpected exception from the pool thread
                        item = self._get_item_by_future_id(future_id)
                        if item:
                            self.queue.update_item_status(
                                item.id,
                                DownloadStatus.FAILED,
                                error_message=str(e)
                            )
                            self.track_failed.emit(item.id, str(e))
                        fail_count += 1
                        continue

                    if self._cancelled:
                        self.queue.update_item_status(
                            item.id,
                            DownloadStatus.CANCELLED,
                            error_message="Cancelled by user"
                        )
                        continue

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

                # Submit new tasks if pool has capacity
                active_count = len(futures)
                slots_available = self.max_workers - active_count

                if slots_available > 0:
                    for _ in range(slots_available):
                        if self._cancelled or self._paused:
                            break

                        item = self.queue.get_next_pending()
                        if not item:
                            break

                        # Mark as downloading and emit signal
                        self.queue.update_item_status(
                            item.id, DownloadStatus.DOWNLOADING, progress=0
                        )
                        self.track_started.emit(item.artist, item.track)

                        # Submit to pool
                        future = executor.submit(self._download_single, item)
                        futures[item.id] = future

                # If no active futures and no pending items, we're done
                if not futures and not self.queue.has_pending():
                    break

                # Brief sleep to avoid busy-waiting
                self.msleep(50)

            # Handle cancellation: cancel remaining futures
            if self._cancelled:
                for future_id, future in futures.items():
                    future.cancel()
                # Wait for running futures to finish
                for future_id, future in futures.items():
                    if not future.cancelled():
                        try:
                            future.result(timeout=5)
                        except Exception:
                            pass

        self.queue.set_running(False)
        self.queue.mark_queue_completed()
        self.all_completed.emit(success_count, fail_count)

    def _get_item_by_future_id(self, item_id: str) -> Optional[QueueItem]:
        """Look up a queue item by its ID."""
        return self.queue.get_item(item_id)

    def _download_single(self, item: QueueItem) -> tuple:
        """
        Download a single track. Runs in a pool thread.

        Returns:
            Tuple of (item, success, file_path, error_message)
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

        # Ensure output directory exists (thread-safe with exist_ok)
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
                    return item, True, expected_path, None

                # Try to find with any extension
                for ext in [audio_format, "mp3", "m4a", "opus", "webm"]:
                    check_path = os.path.join(output_dir, f"{filename}.{ext}")
                    if os.path.exists(check_path):
                        self._embed_metadata(check_path, item)
                        return item, True, check_path, None

                return item, True, None, None
            else:
                error_msg = stderr.strip() if stderr else "Download failed"
                return item, False, None, error_msg

        except FileNotFoundError:
            return item, False, None, "yt-dlp not found. Please install yt-dlp."
        except Exception as e:
            return item, False, None, str(e)

    def _embed_metadata(self, file_path: str, item: QueueItem):
        """Embed metadata into the downloaded file."""
        if not self.config.get("enable_metadata_embedding", True):
            return

        try:
            from downloader.metadata import embed_track_metadata

            track_data = {
                "artist": item.artist,
                "track": item.track
            }
            template = self.config.get("metadata_template", "basic")
            enable_musicbrainz = self.config.get("enable_musicbrainz_lookup", True)

            embed_track_metadata(
                file_path,
                track_data,
                template=template,
                allow_musicbrainz=enable_musicbrainz
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
