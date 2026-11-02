"""Helpers for building extra yt-dlp/ffmpeg CLI arguments from config."""

import shlex

from utils.logger import log_warning


def build_extra_ytdlp_args(config: dict) -> list[str]:
    """
    Build the list of extra CLI arguments to append to a yt-dlp command,
    based on user-supplied config. Lets users pass arbitrary yt-dlp flags
    (e.g. --cookies cookies.txt, --limit-rate 1M) and ffmpeg flags
    (forwarded via yt-dlp's --postprocessor-args) without code changes.
    """
    if not config:
        return []

    args: list[str] = []

    ytdlp_extra = (config.get("ytdlp_extra_args") or "").strip()
    if ytdlp_extra:
        try:
            args.extend(shlex.split(ytdlp_extra))
        except ValueError as e:
            log_warning(f"Ignoring ytdlp_extra_args because it could not be parsed ({e}): {ytdlp_extra}")

    ffmpeg_extra = (config.get("ffmpeg_extra_args") or "").strip()
    if ffmpeg_extra:
        args.extend(["--postprocessor-args", f"ffmpeg:{ffmpeg_extra}"])

    return args
