"""Helpers for building extra yt-dlp/ffmpeg CLI arguments from config."""

import shlex


def build_extra_ytdlp_args(config: dict, speed_limit_divisor: int = 1) -> list[str]:
    """
    Build the list of extra CLI arguments to append to a yt-dlp command,
    based on user-supplied config. Lets users pass arbitrary yt-dlp flags
    (e.g. --cookies cookies.txt, --limit-rate 1M) and ffmpeg flags
    (forwarded via yt-dlp's --postprocessor-args) without code changes.

    speed_limit_divisor: yt-dlp's --limit-rate applies per process. When
    several downloads run in parallel, pass the number of concurrent
    downloads here so the configured limit is split across them and the
    *combined* throughput stays under the user's target.
    """
    if not config:
        return []

    args: list[str] = []

    # Speed limit (Mbps set from the Downloads view slider). Converted to
    # bytes/sec for yt-dlp's --limit-rate. 0 (or invalid) means unlimited.
    try:
        speed_limit_mbps = float(config.get("download_speed_limit_mbps", 0) or 0)
    except (TypeError, ValueError):
        speed_limit_mbps = 0.0
    try:
        divisor = max(1, int(speed_limit_divisor))
    except (TypeError, ValueError):
        divisor = 1
    if speed_limit_mbps > 0:
        # Mbps (megabits/sec) -> bytes/sec: * 1_000_000 / 8, then split
        # across the concurrent downloads so the total respects the limit.
        bytes_per_sec = int(speed_limit_mbps * 1_000_000 / 8 / divisor)
        if bytes_per_sec > 0:
            args.extend(["--limit-rate", str(bytes_per_sec)])

    ytdlp_extra = (config.get("ytdlp_extra_args") or "").strip()
    if ytdlp_extra:
        try:
            args.extend(shlex.split(ytdlp_extra))
        except ValueError:
            pass  # malformed quoting in user input; ignore rather than crash the download

    ffmpeg_extra = (config.get("ffmpeg_extra_args") or "").strip()
    if ffmpeg_extra:
        args.extend(["--postprocessor-args", f"ffmpeg:{ffmpeg_extra}"])

    return args
