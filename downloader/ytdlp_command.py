"""Builds and runs the yt-dlp search download for a single track."""

import math
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from utils.logger import log_warning
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


COOKIE_FLAGS = ("--cookies", "--cookies-from-browser")
RETRY_PLAYER_CLIENTS = "youtube:player_client=tv,web_safari,android"
MIN_NODE_MAJOR = 20


def _uses_cookies(args: list[str]) -> bool:
    """Return whether the extra yt-dlp args sign in with cookies.

    @param args: Extra yt-dlp arguments.
    """
    return any(a in COOKIE_FLAGS or a.startswith(tuple(f + "=" for f in COOKIE_FLAGS)) for a in args)


def _without_cookies(args: list[str]) -> list[str]:
    """Return the extra args with every cookie flag and its value removed.

    @param args: Extra yt-dlp arguments.
    """
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in COOKIE_FLAGS:
            skip = True
        elif not a.startswith(tuple(f + "=" for f in COOKIE_FLAGS)):
            out.append(a)
    return out


def _node_is_supported(path: str) -> bool:
    """Return whether the Node.js at path is new enough for yt-dlp's YouTube challenge solver.

    @param path: Path to the node executable.
    """
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10, **hidden_subprocess_kwargs())
        return int(out.stdout.strip().lstrip("v").split(".")[0]) >= MIN_NODE_MAJOR
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def find_js_runtime() -> Optional[tuple[str, str]]:
    """Return (name, path) of a JavaScript runtime yt-dlp can use for signed-in YouTube downloads, or None."""
    exe = ".exe" if os.name == "nt" else ""
    home = os.path.expanduser("~")
    places = {
        "deno": [shutil.which("deno"), os.path.join(home, ".deno", "bin", "deno" + exe)],
        "node": [
            shutil.which("node"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "nodejs", "node.exe"),
            "/opt/homebrew/bin/node",
            "/usr/local/bin/node",
        ],
    }
    for name, candidates in places.items():
        for path in candidates:
            if path and os.path.isfile(path) and (name == "deno" or _node_is_supported(path)):
                return name, path
    return None


def resolve_extra_args(config: dict) -> list[str]:
    """Return the user's extra yt-dlp args, adding a JS runtime when cookies are used.

    Signed-in YouTube requests need a JavaScript runtime. Without one every download fails, so cookies are
    dropped when no runtime is installed.

    @param config: App config, read for ytdlp_extra_args and ffmpeg_extra_args.
    """
    args = build_extra_ytdlp_args(config)
    if not _uses_cookies(args) or "--js-runtimes" in args:
        return args
    runtime = find_js_runtime()
    if runtime is None:
        log_warning(f"yt-dlp cookies ignored: {NO_JS_RUNTIME_MESSAGE}")
        return _without_cookies(args)
    name, path = runtime
    return args + ["--js-runtimes", f"{name}:{path}"]


def _simplified_title(title: str) -> str:
    """Return the title without bracketed qualifiers or a " - Remastered" style suffix, for a looser retry search.

    @param title: Track title from Spotify.
    """
    core = title.split(" - ", 1)[0]
    core = re.sub(r"[\(\[\{][^\)\]\}]*[\)\]\}]", " ", core)
    return re.sub(r"\s+", " ", core).strip()


def build_search_command(
    track: dict,
    output_dir: str,
    audio_format: str,
    config: Optional[dict],
    *,
    title: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> list[str]:
    """Return the yt-dlp argv that searches YouTube for a track and saves it as audio.

    @param track: Track dict with artist, track and optionally duration_ms.
    @param output_dir: Folder the audio file is written to.
    @param audio_format: Target audio format such as mp3 or flac.
    @param config: App config, read for ytdlp_path, match_duration_tolerance and extra args.
    @param title: Title to search for instead of the track's own, for a retry with a simpler query.
    @param extra_args: Extra yt-dlp args to use instead of reading them from config.
    """
    config = config or {}
    artist, track_title = _track_names(track)
    query = f"{artist} - {title or track_title}"
    output = os.path.join(output_dir, f"{get_base_filename(artist, track_title)}.%(ext)s")

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

    cmd.extend(build_extra_ytdlp_args(config) if extra_args is None else extra_args)
    return cmd


NO_JS_RUNTIME_MESSAGE = "Signed-in YouTube downloads need Node.js 20+ or Deno installed."
SIGN_IN_HINT = (
    "Add --cookies-from-browser chrome (or firefox, edge) to Extra yt-dlp arguments in Settings. "
    "This needs Node.js 20+ or Deno installed."
)
NO_RESULTS_MESSAGE = (
    "YouTube returned no search results. Explicit or age-restricted tracks only show up when signed in. " + SIGN_IN_HINT
)

_ERROR_PATTERNS = (
    (("http error 429", "too many requests"), "YouTube is rate limiting requests (HTTP 429). Wait a while and retry."),
    (("confirm your age",), "This track is age-restricted on YouTube and needs sign-in. " + SIGN_IN_HINT),
    (("sign in to confirm",), "YouTube asked to sign in to confirm you are not a bot. " + SIGN_IN_HINT),
    (("ffmpeg not found", "ffprobe and ffmpeg not found", "ffmpeg is not installed"), "FFmpeg not found. Install FFmpeg or set its path in settings."),
    (("no supported javascript runtime",), "YouTube needs a JavaScript runtime for this download. " + NO_JS_RUNTIME_MESSAGE),
    (("requested format is not available", "only images are available"), "YouTube offered no audio for this video. Retry later, or update yt-dlp."),
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


FINAL_ERRORS = (
    "Cancelled",
    "yt-dlp not found",
    "Could not start yt-dlp",
    "FFmpeg not found",
    "YouTube is rate limiting",
)


def _run_once(
    cmd: list[str],
    output_dir: str,
    base_filename: str,
    tolerance: float,
    popen_hook: Optional[Callable],
    cancel_check: Optional[Callable[[], bool]],
    output_hook: Optional[Callable[[str], None]],
) -> DownloadResult:
    """Run one yt-dlp command and report where the audio file landed.

    @param cmd: The yt-dlp argv.
    @param output_dir: Folder the audio file is written to.
    @param base_filename: "Artist - Track" file stem to look for afterwards.
    @param tolerance: Duration tolerance used in the search, for the error message.
    @param popen_hook: Called with the Popen right after it starts, so a caller can kill it.
    @param cancel_check: Polled while yt-dlp runs, a true result terminates the process.
    @param output_hook: Called with each output line as it arrives.
    """
    from downloader.metadata import find_downloaded_audio_path

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

    explained = describe_ytdlp_error(lines, "")
    if explained and "does not pass filter" not in explained:
        return DownloadResult(False, None, explained)
    if any("does not pass filter" in line.lower() for line in lines):
        return DownloadResult(False, None, f"No search result within {tolerance:g}s of the track length.")
    if not any(line.startswith("[youtube] ") and "Extracting URL" not in line for line in lines):
        return DownloadResult(False, None, NO_RESULTS_MESSAGE)
    return DownloadResult(False, None, "yt-dlp finished but no audio file was found.")


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
    """Search YouTube for one track and download it, retrying with other YouTube clients and then a simpler query.

    @param track: Track dict with artist, track and optionally duration_ms.
    @param output_dir: Folder the audio file is written to.
    @param audio_format: Target audio format such as mp3 or flac.
    @param config: App config passed to build_search_command.
    @param popen_hook: Called with the Popen right after it starts, so a caller can kill it.
    @param cancel_check: Polled while yt-dlp runs, a true result terminates the process.
    @param output_hook: Called with each output line as it arrives.
    """
    config = config or {}
    artist, title = _track_names(track)
    base_filename = get_base_filename(artist, title)
    tolerance = _duration_tolerance(config)
    extra = resolve_extra_args(config)

    attempts = [extra]
    if "--extractor-args" not in extra:
        attempts.append(extra + ["--extractor-args", RETRY_PLAYER_CLIENTS])
    simple = _simplified_title(title)
    titles = [None] + ([simple] if simple and simple != title else [])

    result = DownloadResult(False, None, "yt-dlp finished but no audio file was found.")
    first_error = None
    for search_title in titles:
        for args in attempts:
            cmd = build_search_command(track, output_dir, audio_format, config, title=search_title, extra_args=args)
            result = _run_once(cmd, output_dir, base_filename, tolerance, popen_hook, cancel_check, output_hook)
            if result.success or result.error.startswith(FINAL_ERRORS):
                return result
            first_error = first_error or result.error
    return DownloadResult(False, None, first_error or result.error)
