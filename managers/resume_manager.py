from utils.jsonio import load_json, write_json_atomic
from utils.logger import log_info, log_error
from constants import PROGRESS_FILE

def save_progress(pending_tracks):
    """Write the tracks still to download to the resume file.

    @param pending_tracks: List of track dicts.
    """
    try:
        write_json_atomic(PROGRESS_FILE, pending_tracks)
        log_info("Saved download progress.")
    except Exception as e:
        log_error(f"Failed to save progress: {e}")

def resume_batch(config):
    """Download the tracks in the resume file and keep only the ones that failed again.

    @param config: App config with output_dir and audio_format.
    """
    pending_tracks = load_json(PROGRESS_FILE, None)
    if pending_tracks is None:
        log_info("No saved progress found.")
        return

    if not pending_tracks:
        log_info("No tracks to resume.")
        return

    from downloader.base_downloader import batch_download
    import asyncio

    log_info(f"Resuming batch download of {len(pending_tracks)} tracks...")
    failed = asyncio.run(batch_download(pending_tracks, config["output_dir"], config["audio_format"], config=config))

    save_progress(failed)
    if failed:
        log_info(f"{len(failed)} tracks failed again and stay in the progress file.")
    else:
        log_info("Cleared progress file.")
