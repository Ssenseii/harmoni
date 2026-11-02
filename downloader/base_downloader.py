import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from utils import log_info, log_success, log_error, log_warning
from downloader.ytdlp_command import DownloadResult, get_base_filename, run_download
from tqdm import tqdm


def _get_base_filename(artist: str, track: str) -> str:
    """Generate the base filename used by yt-dlp for consistent metadata embedding."""
    return get_base_filename(artist, track)


def _record_failure(track_dict: dict, output_dir: str, error, config) -> None:
    """Add a failed track to failed_downloads.json, logging instead of raising on errors.

    @param track_dict: The track that failed.
    @param output_dir: Folder the track was meant to land in.
    @param error: Short error message from the download.
    @param config: App config passed through for backups.
    """
    from downloader.retry_manager import add_failed_track

    try:
        add_failed_track(
            (track_dict.get("artist") or "").strip(),
            (track_dict.get("track") or "").strip(),
            error=error,
            config=config,
            track_data=track_dict,
            output_dir=output_dir,
        )
    except Exception as e:
        log_error(f"Could not record failed download: {e}")


def _sleep_between(config) -> float:
    """Return the configured pause between downloads in seconds.

    @param config: App config, read for sleep_between.
    """
    try:
        return max(0.0, float((config or {}).get("sleep_between", 0) or 0))
    except (TypeError, ValueError):
        return 0.0


def _embed_metadata_after_download(
    audio_path: str,
    track: dict,
    config: dict,
) -> bool:
    """Embed metadata into downloaded audio file after successful download."""
    try:
        from downloader.metadata import embed_track_metadata
        
        # Check if metadata embedding is enabled
        if not config.get("enable_metadata_embedding", True):
            return True
        
        # Get metadata template and options
        template = config.get("metadata_template", "basic")
        enable_musicbrainz = config.get("enable_musicbrainz_lookup", True)
        
        # Embed metadata
        return embed_track_metadata(
            audio_path,
            track,
            template=template,
            allow_musicbrainz=enable_musicbrainz,
            config=config,
        )
    except ImportError:
        log_warning("Metadata embedding module not available, skipping metadata embedding")
        return True
    except Exception as e:
        log_error(f"Metadata embedding failed for {audio_path}: {e}")
        return False


def download_track(artist, track, output_dir, audio_format, sleep_between, config=None, track_data=None, record_failure=True):
    """Download one track, embed its metadata and return a DownloadResult.

    @param artist: Artist name.
    @param track: Track title.
    @param output_dir: Folder the audio file is written to.
    @param audio_format: Target audio format such as mp3 or flac.
    @param sleep_between: Seconds to pause after the download.
    @param config: App config.
    @param track_data: Full track dict for metadata and duration matching, artist and track win over its keys.
    @param record_failure: Add the track to failed_downloads.json when the download fails.
    """
    query = f"{artist} - {track}"
    track_dict = dict(track_data or {})
    track_dict["artist"] = artist
    track_dict["track"] = track

    log_info(f"Starting download: {query}")
    try:
        result = run_download(track_dict, output_dir, audio_format, config, output_hook=print)
    except Exception as e:
        result = DownloadResult(False, None, str(e))

    if result.success:
        log_success(f"Downloaded successfully: {query}")
        try:
            if _embed_metadata_after_download(result.path, track_dict, config or {}):
                log_info(f"Metadata embedded for {query}")
            else:
                log_warning(f"Metadata embedding failed for {query}")
        except Exception as e:
            log_warning(f"Metadata embedding step failed: {e}")
    else:
        log_error(f"Failed to download: {query} ({result.error})")
        if record_failure:
            _record_failure(track_dict, output_dir, result.error, config)

    time.sleep(sleep_between)
    return result


def _download_worker(track_dict, output_dir, audio_format, config=None):
    """Download one track inside a batch thread, record a failure and pause for sleep_between.

    @param track_dict: Track dict with artist, track and any metadata.
    @param output_dir: Folder the audio file is written to.
    @param audio_format: Target audio format such as mp3 or flac.
    @param config: App config.
    """
    artist = (track_dict.get("artist") or "").strip()
    track = (track_dict.get("track") or "").strip()
    query = f"{artist} - {track}"

    try:
        result = run_download(track_dict, output_dir, audio_format, config)
    except Exception as e:
        result = DownloadResult(False, None, str(e))

    if result.success:
        log_success(f"Downloaded: {query}")
        try:
            if not _embed_metadata_after_download(result.path, track_dict, config or {}):
                log_warning(f"Metadata embedding failed for {query}")
        except Exception as e:
            log_warning(f"Metadata embedding step failed: {e}")
    else:
        log_error(f"Failed: {query} ({result.error})")
        _record_failure(track_dict, output_dir, result.error, config)

    pause = _sleep_between(config)
    if pause:
        time.sleep(pause)
    return result


async def batch_download(tracks, output_dir, audio_format, max_workers=4, config=None, save_progress_first=False):
    """Download tracks concurrently and return the tracks that failed.

    @param tracks: List of track dicts with artist and track keys.
    @param output_dir: Output directory for downloads.
    @param audio_format: Audio format such as mp3 or flac.
    @param max_workers: Maximum concurrent downloads.
    @param config: Optional config dict for sleep_between, auto-cleanup and backup.
    @param save_progress_first: Save tracks to the resume file before starting and leave only the failures there after.
    """
    if save_progress_first:
        from managers.resume_manager import save_progress
        save_progress(list(tracks))

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        tasks = []
        with tqdm(total=len(tracks), desc="Downloading", unit="track") as pbar:
            for track in tracks:
                task = loop.run_in_executor(executor, _download_worker, track, output_dir, audio_format, config)
                task.add_done_callback(lambda _: pbar.update(1))
                tasks.append(task)
            results = await asyncio.gather(*tasks, return_exceptions=True)

    failed = [
        track for track, result in zip(tracks, results)
        if isinstance(result, BaseException) or not result.success
    ]

    if save_progress_first:
        save_progress(failed)

    # Post-download operations if config is provided
    if config:
        # Auto-backup data files
        if config.get("auto_backup", True):
            try:
                from managers.backup_manager import backup_all
                log_info("Creating backups of data files...")
                backup_all(config)
            except ImportError:
                pass
            except Exception as e:
                log_error(f"Backup failed: {e}")
        
        # Auto-cleanup
        if config.get("auto_cleanup", True):
            try:
                from managers.cleanup_manager import cleanup_after_download
                log_info("Running post-download cleanup...")
                cleanup_results = cleanup_after_download(config)
                total_cleaned = (
                    cleanup_results.get("temp_files_removed", 0) +
                    cleanup_results.get("empty_dirs_removed", 0) +
                    cleanup_results.get("partial_files_removed", 0)
                )
                if total_cleaned > 0:
                    log_info(f"Cleaned up {total_cleaned} items")
            except ImportError:
                pass
            except Exception as e:
                log_error(f"Cleanup failed: {e}")
                
        # Auto-metadata embedding for all downloaded files (legacy batch mode)
        if config.get("auto_metadata_embedding", True) and config.get("enable_metadata_embedding", True):
            try:
                from downloader.metadata import embed_metadata
                log_info("Embedding metadata in all downloaded files...")
                embed_metadata(output_dir)
            except ImportError:
                pass
            except Exception as e:
                log_error(f"Auto metadata embedding failed: {e}")

    return failed
