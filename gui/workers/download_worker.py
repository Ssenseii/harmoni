"""Download worker thread for GUI."""

import glob as globmod
import os
import subprocess
import time
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

        max_retries = self.config.get("retry_attempts", 3)
        retry_delay = self.config.get("retry_delay", 5)
        sleep_between = self.config.get("sleep_between", 5)

        self.queue.set_running(True)

        first_track = True

        while not self._cancelled:
            # Check for pause
            if self._paused:
                self.msleep(100)
                continue

            # Get next pending item
            item = self.queue.get_next_pending()
            if not item:
                break

            # Set max_retries from config on the item
            item.max_retries = max_retries

            # Sleep between different tracks (not the first one)
            if not first_track and sleep_between > 0:
                if not self._interruptible_sleep(sleep_between):
                    break
            first_track = False

            # Mark as downloading
            self.queue.update_item_status(item.id, DownloadStatus.DOWNLOADING, progress=0)
            self.track_started.emit(item.artist, item.track)

            # Download with retry loop
            last_error = None
            succeeded = False

            for attempt in range(max_retries + 1):
                if self._cancelled:
                    break

                # Wait before retry (not before first attempt)
                if attempt > 0:
                    delay = min(retry_delay * (2 ** (attempt - 1)), 60)
                    item.retry_count = attempt
                    retry_msg = f"Retry {attempt}/{max_retries}: {last_error}"
                    self.queue.update_item_status(
                        item.id,
                        DownloadStatus.DOWNLOADING,
                        progress=0,
                        error_message=retry_msg
                    )
                    if not self._interruptible_sleep(delay):
                        break

                if self._cancelled:
                    break

                success, file_path, error = self._download_single(item)

                if success:
                    succeeded = True
                    self.queue.update_item_status(
                        item.id,
                        DownloadStatus.COMPLETED,
                        progress=100,
                        file_path=file_path
                    )
                    self.track_completed.emit(item.id, True, file_path or "")
                    success_count += 1
                    break
                else:
                    last_error = error

            if self._cancelled:
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.CANCELLED,
                    error_message="Cancelled by user"
                )
                break

            if not succeeded:
                if max_retries > 0:
                    final_msg = f"Failed after {max_retries + 1} attempts: {last_error}"
                else:
                    final_msg = last_error or "Unknown error"
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.FAILED,
                    error_message=final_msg
                )
                self.track_failed.emit(item.id, final_msg)
                fail_count += 1

        self.queue.set_running(False)
        self.queue.mark_queue_completed()
        self.all_completed.emit(success_count, fail_count)

    def _interruptible_sleep(self, seconds: float) -> bool:
        """
        Sleep for the given duration, checking for cancel/pause.

        Returns False if cancelled (caller should break), True otherwise.
        """
        end_time = time.monotonic() + seconds
        while time.monotonic() < end_time:
            if self._cancelled:
                return False
            if self._paused:
                self.msleep(100)
                continue
            self.msleep(100)
        return True

    def _download_single(self, item: QueueItem) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Download a single track.

        Returns:
            Tuple of (success, file_path, error_message)
        """
        output_dir = self.config.get("output_dir", "music")
        audio_format = self.config.get("audio_format", "mp3")
        timeout = self.config.get("download_timeout", 300)

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

            try:
                # Wait for completion with timeout
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                # Clean up partial files
                self._cleanup_partial_files(output_dir, filename)
                return False, None, f"Download timed out after {timeout}s"

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

    def _cleanup_partial_files(self, output_dir: str, filename: str):
        """Remove partial download files after a timeout or failure."""
        try:
            pattern = os.path.join(output_dir, f"{filename}.*")
            for f in globmod.glob(pattern):
                # Also match .part files left by yt-dlp
                os.remove(f)
            # yt-dlp sometimes uses .part suffix
            part_pattern = os.path.join(output_dir, f"{filename}.*.part")
            for f in globmod.glob(part_pattern):
                os.remove(f)
        except OSError:
            pass

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
