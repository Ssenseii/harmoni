import os
import json
from utils.logger import log_info, log_error, log_success
from downloader.base_downloader import batch_download

"""
Downloads all pending tracks for a given playlist.
Creates the playlist folder if it doesn't exist.
"""
async def download_playlist(playlist_name, tracks, output_dir, audio_format, sleep_between, config=None):
    sanitized_name = playlist_name.replace("/", "-").strip()
    playlist_dir = os.path.join(output_dir, sanitized_name)

    os.makedirs(playlist_dir, exist_ok=True)

    log_info(f"Downloading playlist: {playlist_name} → {len(tracks)} tracks")

    # Pass complete track dictionaries to preserve all metadata
    failed = await batch_download(tracks, playlist_dir, audio_format, config=config)
    if failed:
        log_error(f"Finished playlist {playlist_name} with {len(failed)} failed tracks. Use Retry failed downloads to try them again.")
    else:
        log_success(f"Finished downloading playlist: {playlist_name}")
    return failed
