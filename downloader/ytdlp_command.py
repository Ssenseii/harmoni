"""Builds and runs the yt-dlp search download for a single track."""

import math
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from utils.system import hidden_subprocess_kwargs
from utils.ytdlp_args import build_extra_ytdlp_args

DEFAULT_DURATION_TOLERANCE = 15
MAX_DOWNLOADS_REACHED = 101


@dataclass
class DownloadResult:
    """Outcome of one track download."""

    success: bool
    path: Optional[str] = None
    error: Optional[str] = None


def get_base_filename(artist: str, track: str) -> str:
    """Return the "Artist - Track" file stem yt-dlp writes, with forward and back slashes made safe.

    @param artist: Artist name.
    @param track: Track title.
    """
    return f"{artist} - {track}".replace("/", "-").replace("\\", "-")


def _track_names(track: dict) -> tuple[str, str]:
    """Return the stripped artist and track title from a track dict.

    @param track: Track dict with "artist" and "track" keys.
    """
    return (track.get("artist") or "").strip(), (track.get("track") or "").strip()


def _duration_seconds(track: dict) -> Optional[float]:
    """Return the track length in seconds from duration_ms, or None when missing or invalid.

    @param track: Track dict that may carry duration_ms as an int or a string.
    """
    try:
        ms = float(track.get("duration_ms"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(ms) or ms <= 0:
        return None
    return ms / 1000.0


def _duration_tolerance(config: dict) -> float:
    """Return the allowed difference in seconds between the track and the video length.

    @param config: App config, read for match_duration_tolerance.
    """
    try:
        return max(0.0, float(config.get("match_duration_tolerance", DEFAULT_DURATION_TOLERANCE)))
    except (TypeError, ValueError):
        return float(DEFAULT_DURATION_TOLERANCE)


def _ffmpeg_location() -> Optional[str]:
    """Return the ffmpeg path to hand to yt-dlp, or None when ffmpeg cannot be found."""
    from utils.ffmpeg import get_ffmpeg_path

    try:
        return get_ffmpeg_path()
    except FileNotFoundError:
        return None


def build_search_command(track: dict, output_dir: str, audio_format: str, config: Optional[dict]) -> list[str]:
    """Return the yt-dlp argv that searches YouTube for a track and saves it as audio.

    @param track: Track dict with artist, track and optionally duration_ms.
    @param output_dir: Folder the audio file is written to.
    @param audio_format: Target audio format such as mp3 or flac.
    @param config: App config, read for ytdlp_path, match_duration_tolerance and extra args.
    """
    config = config or {}
    artist, title = _track_names(track)
    query = f"{artist} - {title}"
    output = os.path.join(output_dir, f"{get_base_filename(artist, title)}.%(ext)s")

    cmd = [(config.get("ytdlp_path") or "").strip() or "yt-dlp"]

    seconds = _duration_seconds(track)
    if seconds is None:
        cmd.append(f"ytsearch1:{query}")
    else:
        tolerance = _duration_tolerance(config)
        low = max(0, math.floor(seconds - tolerance))
        high = math.ceil(seconds + tolerance)
        cmd += [
            f"ytsearch5:{query}",
            "--match-filter", f"duration > {low} & duration < {high}",
            "--max-downloads", "1",
        ]

    cmd += ["--no-playlist", "-x", "--audio-format", audio_format, "-o", output]

    ffmpeg = _ffmpeg_location()
    if ffmpeg:
        cmd += ["--ffmpeg-location", ffmpeg]

    cmd.extend(build_extra_ytdlp_args(config))
    return cmd


SIGN_IN_HINT = "Add --cookies-from-browser chrome (or firefox, edge) to Extra yt-dlp arguments in Settings."
NO_RESULTS_MESSAGE = (
    "YouTube returned no search results. Explicit or age-restricted tracks only show up when signed in. " + SIGN_IN_HINT
)

_ERROR_PATTERNS = (
    (("http error 429", "too many requests"), "YouTube is rate limiting requests (HTTP 429). Wait a while and retry."),
    (("confirm your age",), "This track is age-restricted on YouTube and needs sign-in. " + SIGN_IN_HINT),
    (("sign in to confirm",), "YouTube asked to sign in to confirm you are not a bot. " + SIGN_IN_HINT),
    (("ffmpeg not found", "ffprobe and ffmpeg not found", "ffmpeg is not installed"), "FFmpeg not found. Install FFmpeg or set its path in settings."),
    (("does not pass filter",), "No search result matched the track length."),
    (("no video results", "no results"), "No YouTube results for this track."),
)


def describe_ytdlp_error(lines: list[str], fallback: str) -> str:
    """Turn yt-dlp output into a short error message.

    @param lines: Output lines from yt-dlp, stdout and stderr merged.
    @param fallback: Message returned when no line explains the failure.
    """
    text = "\n".join(lines).lower()
    for needles, message in _ERROR_PATTERNS:
        if any(n in text for n in needles):
            return message
    for line in reversed(lines):
        if line.strip().startswith("ERROR:"):
            return line.strip()
    return fallback


def _drain(stream, lines: list[str], output_hook: Optional[Callable[[str], None]]) -> None:
    """Read a text stream line by line into lines until it closes.

    @param stream: The process stdout.
    @param lines: List that receives each line without its newline.
    @param output_hook: Optional callback for each line.
    """
    try:
        for raw in stream:
            line = raw.rstrip("\r\n")
            lines.append(line)
            if output_hook:
                # A failing hook must not stop the drain, or yt-dlp blocks on a full pipe.
                try:
                    output_hook(line)
                except Exception:
                    pass
    except (OSError, ValueError):
        pass


def _stop_process(process) -> None:
    """Terminate a process, killing it when it does not exit within five seconds.

    @param process: The running Popen.
    """
    try:
        process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    except OSError:
        pass


def run_download(
    track: dict,
    output_dir: str,
    audio_format: str,
    config: Optional[dict],
    *,
    popen_hook: Optional[Callable] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    output_hook: Optional[Callable[[str], None]] = None,
) -> DownloadResult:
    """Run the yt-dlp search download for one track and report where the file landed.

    @param track: Track dict with artist, track and optionally duration_ms.
    @param output_dir: Folder the audio file is written to.
    @param audio_format: Target audio format such as mp3 or flac.
    @param config: App config passed to build_search_command.
    @param popen_hook: Called with the Popen right after it starts, so a caller can kill it.
    @param cancel_check: Polled while yt-dlp runs, a true result terminates the process.
    @param output_hook: Called with each output line as it arrives.
    """
    from downloader.metadata import find_downloaded_audio_path

    config = config or {}
    cmd = build_search_command(track, output_dir, audio_format, config)
    artist, title = _track_names(track)
    base_filename = get_base_filename(artist, title)

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )
    except FileNotFoundError:
        return DownloadResult(False, None, "yt-dlp not found. Please install yt-dlp.")
    except OSError as e:
        return DownloadResult(False, None, f"Could not start yt-dlp: {e}")

    if popen_hook:
        popen_hook(process)

    lines: list[str] = []
    reader = threading.Thread(target=_drain, args=(process.stdout, lines, output_hook), daemon=True)
    reader.start()

    cancelled = False
    while process.poll() is None:
        if cancel_check and cancel_check():
            cancelled = True
            _stop_process(process)
            break
        time.sleep(0.1)

    returncode = process.wait()
    reader.join(timeout=5)

    if cancelled:
        return DownloadResult(False, None, "Cancelled")

    if returncode not in (0, MAX_DOWNLOADS_REACHED):
        return DownloadResult(False, None, describe_ytdlp_error(lines, f"yt-dlp exited with code {returncode}"))

    path = find_downloaded_audio_path(output_dir, base_filename)
    if path:
        return DownloadResult(True, path, None)

    if any("does not pass filter" in line.lower() for line in lines):
        tolerance = _duration_tolerance(config)
        return DownloadResult(False, None, f"No search result within {tolerance:g}s of the track length.")
    if not any(line.startswith("[youtube] ") and "Extracting URL" not in line for line in lines):
        return DownloadResult(False, None, describe_ytdlp_error(lines, NO_RESULTS_MESSAGE))
    return DownloadResult(False, None, describe_ytdlp_error(lines, "yt-dlp finished but no audio file was found."))
