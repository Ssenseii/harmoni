import os
import subprocess
import json
import questionary
from utils.logger import log_info, log_success, log_error
from utils.ytdlp_args import build_extra_ytdlp_args
from utils.system import hidden_subprocess_kwargs

def get_youtube_info(url):
    """
    Fetches video/playlist metadata using yt-dlp in JSON format.
    """
    try:
        result = subprocess.run(
            ["yt-dlp", "-j", "--flat-playlist", url],
            capture_output=True,
            text=True,
            **hidden_subprocess_kwargs()
        )
        if result.returncode != 0:
            log_error(f"Failed to fetch info for {url}")
            return None

        # For playlist, yt-dlp outputs one JSON per line
        lines = result.stdout.strip().split("\n")
        data = []
        for line in lines:
            if line.strip():
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip invalid JSON lines
                    continue
        return data
    except Exception as e:
        log_error(f"Error fetching info: {e}")
        return None


def download_from_link(url, output_dir, audio_format, config=None):
    """
    Download a single YouTube video after confirming title.
    """
    log_info(f"Fetching info for video: {url}")
    data = get_youtube_info(url)

    if not data or len(data) == 0:
        log_error("No data found.")
        return

    # Single video info
    title = data[0].get("title", "Unknown Title")

    if not questionary.confirm(f"Download this video?\n\nTitle: {title}").ask():
        log_info("Cancelled by user.")
        return

    cmd = [
        "yt-dlp",
        url,
        "--no-playlist",
        "-x", "--audio-format", audio_format,
        "-o", os.path.join(output_dir, "%(title)s.%(ext)s")
    ]
    cmd.extend(build_extra_ytdlp_args(config))
    result = subprocess.run(cmd)
    if result.returncode == 0:
        log_success(f"Downloaded: {title}")
    else:
        log_error(f"Failed to download: {title}")


def download_from_playlist(url, output_dir, audio_format, sleep_between, config=None):
    """
    Download all videos from a playlist after confirming contents.
    """
    log_info(f"Fetching playlist info: {url}")
    data = get_youtube_info(url)

    if not data or len(data) == 0:
        log_error("No data found.")
        return

    # Playlist name may not be in flat playlist data, but the first entry has it
    playlist_title = data[0].get("playlist_title", "Unknown Playlist")
    video_titles = [entry.get("title", "Unknown Title") for entry in data]

    playlist_preview = "\n".join([f"{i+1}. {t}" for i, t in enumerate(video_titles[:10])])
    if len(video_titles) > 10:
        playlist_preview += f"\n... and {len(video_titles) - 10} more"

    if not questionary.confirm(
        f"Download this playlist?\n\nPlaylist: {playlist_title}\n\nTracks:\n{playlist_preview}"
    ).ask():
        log_info("Cancelled by user.")
        return

    cmd = [
        "yt-dlp",
        url,
        "-x", "--audio-format", audio_format,
        "-o", os.path.join(output_dir, "%(title)s.%(ext)s")
    ]
    cmd.extend(build_extra_ytdlp_args(config))
    result = subprocess.run(cmd)
    if result.returncode == 0:
        log_success(f"Downloaded playlist: {playlist_title}")
    else:
        log_error(f"Failed to download playlist: {playlist_title}")
