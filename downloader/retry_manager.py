import os
import threading
import time
from downloader.base_downloader import download_track
from downloader.ytdlp_command import DownloadResult
from utils.jsonio import load_json, write_json_atomic
from utils.logger import log_info, log_error, log_warning
from constants import FAILED_FILE

_BOOKKEEPING_KEYS = ("attempt_count", "last_error", "output_dir")
_failed_file_lock = threading.Lock()


def _backup_failed_file(config):
    """Back up failed_downloads.json when auto_backup is on.

    @param config: App config passed to backup_json_file.
    """
    if config and not config.get("auto_backup", True):
        return
    try:
        from managers.backup_manager import backup_json_file
        backup_json_file(FAILED_FILE, config)
    except ImportError:
        pass


def _track_fields(entry: dict) -> dict:
    """Return the track data stored in a failed entry without retry bookkeeping.

    @param entry: One item from failed_downloads.json.
    """
    return {k: v for k, v in entry.items() if k not in _BOOKKEEPING_KEYS}


def retry_failed(config):
    """
    Retry failed downloads using configurable retry rules from config.

    Config options used:
    - retry_attempts: Maximum number of retry attempts per track
    - retry_delay: Base delay between retries (uses exponential backoff)
    - auto_backup: Whether to backup before modifying failed_downloads.json
    """
    if not os.path.exists(FAILED_FILE):
        log_info("No failed downloads to retry.")
        return

    # Get retry configuration
    max_attempts = config.get("retry_attempts", 3)
    base_delay = config.get("retry_delay", 5)

    if max_attempts == 0:
        log_info("Retry is disabled (retry_attempts=0).")
        return

    failed_tracks = load_json(FAILED_FILE, [])
    if not isinstance(failed_tracks, list):
        log_error("Failed downloads file does not hold a list.")
        return

    if not failed_tracks:
        log_info("No failed downloads.")
        return

    _backup_failed_file(config)

    log_info(f"Retrying {len(failed_tracks)} failed downloads (max {max_attempts} attempts each)...")
    still_failed = []

    for t in failed_tracks:
        track_attempts = t.get("attempt_count", 0)

        if track_attempts >= max_attempts:
            log_warning(f"Skipping {t['artist']} - {t['track']} (exceeded max attempts: {track_attempts})")
            still_failed.append(t)
            continue

        success = False
        attempts_made = 0
        last_error = t.get("last_error")

        for attempt in range(1, max_attempts - track_attempts + 1):
            # Exponential backoff delay
            delay = base_delay * (2 ** (attempt - 1))

            log_info(f"Retry attempt {attempt}/{max_attempts - track_attempts} for: {t['artist']} - {t['track']}")
            attempts_made += 1

            try:
                result = download_track(
                    t["artist"],
                    t["track"],
                    t.get("output_dir") or config["output_dir"],
                    config["audio_format"],
                    config.get("sleep_between", 0),
                    config=config,
                    track_data=_track_fields(t),
                    record_failure=False,
                )
            except Exception as e:
                result = DownloadResult(False, None, str(e))

            if result.success:
                success = True
                log_info(f"Successfully downloaded on retry: {t['artist']} - {t['track']}")
                break

            last_error = result.error
            log_error(f"Retry attempt {attempt} failed: {t['artist']} - {t['track']} - {last_error}")

            if attempt < max_attempts - track_attempts:
                log_info(f"Waiting {delay}s before next attempt...")
                time.sleep(delay)

        if not success:
            t["attempt_count"] = track_attempts + attempts_made
            t["last_error"] = last_error
            still_failed.append(t)

    with _failed_file_lock:
        write_json_atomic(FAILED_FILE, still_failed)

    # Summary
    retried_count = len(failed_tracks) - len(still_failed)
    log_info(f"Retry complete: {retried_count} succeeded, {len(still_failed)} still failed.")


def add_failed_track(artist: str, track: str, error: str = None, config: dict = None, track_data: dict = None, output_dir: str = None):
    """Add a track to the failed downloads list with retry tracking, safe to call from several threads.

    @param artist: Artist name.
    @param track: Track title.
    @param error: Short error message from the failed download.
    @param config: App config, used for backups.
    @param track_data: Full track dict kept so a retry has the same metadata and duration.
    @param output_dir: Folder the track was meant to land in.
    """
    with _failed_file_lock:
        failed_tracks = load_json(FAILED_FILE, [])
        if not isinstance(failed_tracks, list):
            failed_tracks = []

        for t in failed_tracks:
            if t.get("artist") == artist and t.get("track") == track:
                t["attempt_count"] = t.get("attempt_count", 0) + 1
                t["last_error"] = error
                break
        else:
            entry = _track_fields(track_data or {})
            entry.update({
                "artist": artist,
                "track": track,
                "attempt_count": 1,
                "last_error": error,
            })
            if output_dir:
                entry["output_dir"] = output_dir
            failed_tracks.append(entry)

        if config:
            _backup_failed_file(config)
        write_json_atomic(FAILED_FILE, failed_tracks)


def clear_failed_tracks():
    """Clear all failed tracks from the list."""
    if os.path.exists(FAILED_FILE):
        with _failed_file_lock:
            write_json_atomic(FAILED_FILE, [])
        log_info("Cleared failed downloads list.")


def get_failed_count() -> int:
    """Get the count of failed downloads."""
    failed = load_json(FAILED_FILE, [])
    return len(failed) if isinstance(failed, list) else 0
