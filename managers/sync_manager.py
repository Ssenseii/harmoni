import os
import time
import hashlib
from datetime import datetime
from typing import List, Optional
from utils.logger import log_info, log_warning, log_error
from utils.loaders import load_exportify_tracks
from utils.jsonio import load_json, write_json_atomic
from constants import APP_DIR

# State file to track synced files
SYNC_STATE_FILE = os.path.join(APP_DIR, "data", "sync_state.json")


def get_file_hash(filepath: str) -> str:
    """Calculate MD5 hash of a file for change detection."""
    hasher = hashlib.md5()
    with open(filepath, "rb") as f:
        buf = f.read(65536)
        while buf:
            hasher.update(buf)
            buf = f.read(65536)
    return hasher.hexdigest()


def load_sync_state() -> dict:
    """Load the sync state from file."""
    return load_json(SYNC_STATE_FILE, {"synced_files": {}, "last_sync": None})


def save_sync_state(state: dict):
    """Save the sync state to file."""
    write_json_atomic(SYNC_STATE_FILE, state, indent=2)


def detect_new_files(exportify_dir: str) -> List[dict]:
    """
    Detect new or modified CSV files in the exportify directory.

    Returns:
        List of dicts with file info for new/modified files
    """
    if not os.path.exists(exportify_dir):
        return []

    state = load_sync_state()
    synced_files = state.get("synced_files", {})

    new_files = []

    for filename in os.listdir(exportify_dir):
        if not filename.lower().endswith(".csv"):
            continue

        filepath = os.path.join(exportify_dir, filename)
        current_hash = get_file_hash(filepath)

        # Check if file is new or modified
        if filename not in synced_files or synced_files[filename]["hash"] != current_hash:
            new_files.append(
                {
                    "filename": filename,
                    "filepath": filepath,
                    "hash": current_hash,
                    "is_new": filename not in synced_files,
                }
            )

    return new_files


def sync_exportify_folder(config: dict) -> dict:
    """
    Sync the exportify folder.

    CSV-first behavior:
    - Detect new/modified Exportify CSVs
    - Parse those CSVs directly into track dictionaries
    - Update sync_state.json to avoid re-processing unchanged files

    Backward compatibility:
    - If tracks_file is a JSON file AND sync_write_tracks_json is enabled,
      this will also merge new tracks into tracks.json.
    """
    exportify_dir = config.get("exportify_watch_folder", "data/exportify")
    tracks_file = config.get("tracks_file", "data/tracks.json")
    auto_backup = config.get("auto_backup", True)

    sync_write_tracks_json = config.get("sync_write_tracks_json", True)
    should_update_tracks_json = (
        bool(sync_write_tracks_json)
        and isinstance(tracks_file, str)
        and tracks_file.lower().endswith(".json")
    )

    results = {
        "new_files": 0,
        "updated_files": 0,
        "new_tracks": 0,
        "tracks_file_updated": False,
        "errors": [],
    }

    if not os.path.exists(exportify_dir):
        log_warning(f"Exportify directory not found: {exportify_dir}")
        results["errors"].append(f"Directory not found: {exportify_dir}")
        return results

    # Detect new/modified files
    new_files = detect_new_files(exportify_dir)

    if not new_files:
        log_info("No new or modified files to sync")
        return results

    log_info(f"Found {len(new_files)} file(s) to sync")

    # Load existing tracks only if we are updating tracks.json
    existing_tracks = []
    existing_ids = set()

    if should_update_tracks_json and os.path.exists(tracks_file):
        # Backup tracks.json before modifying
        if auto_backup:
            try:
                from managers.backup_manager import backup_json_file

                backup_json_file(tracks_file, config)
            except ImportError:
                pass

        existing_tracks = load_json(tracks_file, {}).get("tracks", [])

    # Create set of existing track identifiers for deduplication
    for t in existing_tracks:
        track_id = f"{t.get('artist', '').casefold()}|{t.get('track', '').casefold()}"
        existing_ids.add(track_id)

    # Load sync state
    state = load_sync_state()

    # Process each new file directly
    for file_info in new_files:
        try:
            csv_tracks = load_exportify_tracks(file_info["filepath"])

            added_count = 0
            for track in csv_tracks:
                track_id = f"{track.get('artist', '').casefold()}|{track.get('track', '').casefold()}"
                if track_id in existing_ids:
                    continue

                existing_ids.add(track_id)
                added_count += 1

                if should_update_tracks_json:
                    existing_tracks.append(
                        {
                            "artist": track.get("artist", ""),
                            "album": track.get("album", ""),
                            "track": track.get("track", ""),
                            "uri": track.get("uri", ""),
                        }
                    )

            results["new_tracks"] += added_count
            log_info(f"Synced {file_info['filename']}: {added_count} new tracks")

            # Update sync state for this file
            state["synced_files"][file_info["filename"]] = {
                "hash": file_info["hash"],
                "synced_at": datetime.now().isoformat(),
            }

            if file_info["is_new"]:
                results["new_files"] += 1
            else:
                results["updated_files"] += 1

        except Exception as e:
            error_msg = f"Error syncing {file_info['filename']}: {e}"
            log_error(error_msg)
            results["errors"].append(error_msg)

    # Save updated tracks.json (optional)
    if should_update_tracks_json:
        try:
            write_json_atomic(tracks_file, {"tracks": existing_tracks}, indent=2)
            results["tracks_file_updated"] = True
            log_info(f"Updated {tracks_file} with {results['new_tracks']} new tracks")
        except IOError as e:
            error_msg = f"Failed to save tracks: {e}"
            log_error(error_msg)
            results["errors"].append(error_msg)
    else:
        log_info(
            "CSV-first sync complete (tracks_file not updated). "
            "Downloads can run directly from CSV via primary_input_source=csv."
        )

    # Save sync state
    state["last_sync"] = datetime.now().isoformat()
    save_sync_state(state)

    return results


def schedule_sync(config: dict, interval_seconds: Optional[int] = None):
    """
    Run sync on a schedule.

    Args:
        config: Configuration dict
        interval_seconds: Sync interval in seconds (overrides config)
    """
    import schedule

    interval = interval_seconds or config.get("auto_sync_interval", 3600)

    def sync_job():
        log_info("Running scheduled sync...")
        results = sync_exportify_folder(config)
        if results["new_tracks"] > 0:
            log_info(f"Scheduled sync complete: {results['new_tracks']} new tracks added")
        else:
            log_info("Scheduled sync complete: no new tracks")

    # Schedule recurring sync
    schedule.every(interval).seconds.do(sync_job)

    log_info(f"Sync scheduled every {interval} seconds. Press Ctrl+C to stop.")

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        log_info("Sync scheduler stopped")


def run_sync_once(config: dict) -> dict:
    """Run a single sync operation."""
    return sync_exportify_folder(config)


def get_sync_status(config: dict) -> dict:
    """
    Get current sync status and pending files.

    Returns:
        Dict with sync status information
    """
    exportify_dir = config.get("exportify_watch_folder", "data/exportify")
    state = load_sync_state()

    status = {
        "last_sync": state.get("last_sync"),
        "synced_files_count": len(state.get("synced_files", {})),
        "pending_files": [],
        "auto_sync_enabled": config.get("auto_sync_enabled", False),
        "sync_interval": config.get("auto_sync_interval", 3600),
    }

    # Check for pending files
    pending = detect_new_files(exportify_dir)
    status["pending_files"] = [f["filename"] for f in pending]
    status["pending_count"] = len(pending)

    return status


def clear_sync_state():
    """Clear the sync state to force re-sync of all files."""
    save_sync_state({"synced_files": {}, "last_sync": None})
    log_info("Sync state cleared - all files will be re-synced on next run")

