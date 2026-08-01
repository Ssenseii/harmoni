"""Download worker thread for GUI."""

import os
import re
import subprocess
from typing import Optional

from PySide6.QtCore import QThread, Signal

from gui.workers.download_queue import DownloadQueue, DownloadStatus, QueueItem
from utils.ytdlp_args import build_extra_ytdlp_args


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
        """Process all pending downloads in the queue (parallel)."""
        import threading
        from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait

        from utils.ffmpeg import configure_ffmpeg_path

        # Configure FFmpeg path
        try:
            configure_ffmpeg_path()
        except FileNotFoundError as e:
            for item in self.queue.get_pending_items():
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.FAILED,
                    error_message=str(e)
                )
                self.track_failed.emit(item.id, str(e))
            return

        max_workers = int(self.config.get("concurrent_downloads", 3))
        max_workers = max(1, min(max_workers, 8))
        # Used so the per-process --limit-rate is split across concurrent
        # downloads and the combined speed respects the configured limit.
        self._max_workers = max_workers

        success_count = 0
        fail_count = 0
        count_lock = threading.Lock()

        self.queue.set_running(True)

        # Retry config (previously saved but never applied in the GUI).
        try:
            max_attempts = max(1, int(self.config.get("retry_attempts", 3)) + 1)
        except (TypeError, ValueError):
            max_attempts = 1
        try:
            retry_delay = max(0.0, float(self.config.get("retry_delay", 5)))
        except (TypeError, ValueError):
            retry_delay = 5.0

        def process_item(item):
            nonlocal success_count, fail_count
            self.queue.update_item_status(item.id, DownloadStatus.DOWNLOADING, progress=0)
            self.track_started.emit(item.artist, item.track)

            def on_progress(pct, speed="", eta=""):
                it = self.queue.get_item(item.id)
                if it is not None:
                    it.speed = speed
                    it.eta = eta
                self.queue.update_item_status(
                    item.id, DownloadStatus.DOWNLOADING, progress=pct
                )
                self.track_progress.emit(item.id, pct)

            # Try the download, retrying on failure per retry_attempts.
            success, file_path, error = False, None, None
            for attempt in range(1, max_attempts + 1):
                if self._cancelled:
                    break
                success, file_path, error = self._download_single(item, on_progress)
                if success or self._cancelled:
                    break
                if attempt < max_attempts:
                    # Exponential backoff, but stop early if cancelled.
                    delay = retry_delay * (2 ** (attempt - 1))
                    waited = 0.0
                    while waited < delay and not self._cancelled:
                        self.msleep(100)
                        waited += 0.1

            if self._cancelled:
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.CANCELLED,
                    error_message="Cancelled by user"
                )
                return

            if success:
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.COMPLETED,
                    progress=100,
                    file_path=file_path
                )
                self.track_completed.emit(item.id, True, file_path or "")
                with count_lock:
                    success_count += 1
            else:
                self.queue.update_item_status(
                    item.id,
                    DownloadStatus.FAILED,
                    error_message=error
                )
                self.track_failed.emit(item.id, error or "Unknown error")
                with count_lock:
                    fail_count += 1

        futures = set()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while not self._cancelled:
                # Pause: don't submit new items, let running ones finish
                if self._paused:
                    self.msleep(100)
                    continue

                # Fill available slots
                while len(futures) < max_workers:
                    item = self.queue.get_next_pending()
                    if not item:
                        break
                    # Reserve the item so it isn't picked twice
                    item.status = DownloadStatus.DOWNLOADING
                    futures.add(executor.submit(process_item, item))

                if not futures:
                    break  # nothing running, nothing pending

                done, futures = wait(futures, timeout=0.2, return_when=FIRST_COMPLETED)

            # Wait for any still-running downloads to finish
            if futures:
                wait(futures)

        self.queue.set_running(False)
        self._write_failed_report()
        self._post_download_maintenance()
        self.queue.mark_queue_completed()
        self.all_completed.emit(success_count, fail_count)

    def _post_download_maintenance(self):
        """Run the existing cleanup/backup managers after a download run."""
        # Clean up temp/partial files left in the output folder.
        if self.config.get("auto_cleanup", False):
            try:
                from managers.cleanup_manager import cleanup_after_download
                # Point the cleaner at the resolved (absolute) output folder.
                cleanup_after_download({**self.config, "output_dir": self._resolve_output_dir()})
            except Exception:
                pass  # maintenance must never break the run

        # Back up the data files (tracks.json / playlists.json).
        if self.config.get("auto_backup", True):
            try:
                from managers.backup_manager import backup_all
                backup_all(self.config)
            except Exception:
                pass

    def _write_failed_report(self):
        """Write a txt list of tracks that failed to download into the output folder."""
        failed = [i for i in self.queue.items if i.status == DownloadStatus.FAILED]
        report_path = os.path.join(self._resolve_output_dir(), "inmeyen_sarkilar.txt")

        try:
            if not failed:
                # Nothing failed this run — remove any stale report.
                if os.path.exists(report_path):
                    os.remove(report_path)
                return

            from datetime import datetime

            lines = [
                f"# Inmeyen sarkilar - {datetime.now():%Y-%m-%d %H:%M}",
                f"# Toplam: {len(failed)}",
                "",
            ]
            for i in failed:
                reason = (i.error_message or "Bilinmeyen hata").strip().replace("\n", " ")
                lines.append(f"{i.artist} - {i.track}\t| {reason}")

            with open(report_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            pass  # reporting must never break the download run

    def _resolve_output_dir(self) -> str:
        """Resolve the output directory to an absolute path (project-root relative)."""
        output_dir = self.config.get("output_dir", "music")
        if not os.path.isabs(output_dir):
            import sys
            if getattr(sys, 'frozen', False):
                # Running as compiled executable
                base_dir = os.path.dirname(sys.executable)
            else:
                # Running as script (…/gui/workers/download_worker.py -> project root)
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(base_dir, output_dir)
        return output_dir

    def _download_single(self, item: QueueItem, progress_cb=None) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Download a single track.

        progress_cb: optional callable(percent: int) invoked as the download
        advances so the GUI can show per-track progress.

        Returns:
            Tuple of (success, file_path, error_message)
        """
        output_dir = self._resolve_output_dir()
        audio_format = self.config.get("audio_format", "mp3")

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        query = f"{item.artist} - {item.track}"
        filename = query.replace("/", "-").replace("\\", "-")

        # Skip if this track was already downloaded to the output folder.
        if self.config.get("skip_existing_files", True):
            expected = os.path.join(output_dir, f"{filename}.{audio_format}")
            if os.path.exists(expected):
                return True, expected, None
            # Fall back to a normalized match: handles case/punctuation and any
            # audio extension, using the shared track checker.
            try:
                from utils.track_checker import track_key, existing_track_keys_in_dir
                key = track_key({"artist": item.artist, "track": item.track})
                if key in existing_track_keys_in_dir(output_dir):
                    return True, None, None
            except Exception:
                pass  # matching is best-effort; fall through to downloading

        cmd = [
            "yt-dlp",
            f"ytsearch1:{query}",
            "-x",
            "--audio-format", audio_format,
            "-o", os.path.join(output_dir, f"{filename}.%(ext)s"),
            "--no-playlist",
            "--quiet",
            "--progress",
            "--newline"  # emit each progress update on its own line so we can parse it
        ]
        cmd.extend(build_extra_ytdlp_args(
            self.config,
            speed_limit_divisor=getattr(self, "_max_workers", 1),
        ))

        # Gentle pacing: sleep before each download to avoid rate-limiting.
        try:
            sleep_between = float(self.config.get("sleep_between", 0) or 0)
        except (TypeError, ValueError):
            sleep_between = 0.0
        if sleep_between > 0:
            cmd.extend(["--sleep-interval", f"{sleep_between:g}"])

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # merge so progress/errors come on one stream
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            # Read line by line, parsing yt-dlp's "[download]  45.2% of ..." lines.
            output_lines = []
            percent_re = re.compile(r"(\d{1,3}(?:\.\d+)?)%")
            speed_re = re.compile(r"at\s+([\d.]+\s*[KMGT]?i?B/s)")
            eta_re = re.compile(r"ETA\s+([\d:]+)")
            last_pct = -1
            for line in process.stdout:
                output_lines.append(line)
                if self._cancelled:
                    break
                match = percent_re.search(line)
                if match and progress_cb:
                    try:
                        pct = int(float(match.group(1)))
                    except ValueError:
                        continue
                    pct = max(0, min(pct, 100))
                    # Only report on whole-percent changes to limit signal spam.
                    if pct != last_pct:
                        last_pct = pct
                        sp = speed_re.search(line)
                        et = eta_re.search(line)
                        speed = sp.group(1).replace(" ", "") if sp else ""
                        eta = et.group(1) if et else ""
                        progress_cb(pct, speed, eta)
            process.wait()

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
                # Prefer explicit ERROR lines; fall back to the last output line.
                error_lines = [ln.strip() for ln in output_lines if "ERROR" in ln]
                if error_lines:
                    error_msg = error_lines[-1]
                else:
                    non_empty = [ln.strip() for ln in output_lines if ln.strip()]
                    error_msg = non_empty[-1] if non_empty else "Download failed"
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