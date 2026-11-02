"""Read public Spotify playlists, albums and tracks from Spotify's embed pages, which need no login or developer app."""

import json
import re
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

EMBED_URL = "https://open.spotify.com/embed/{kind}/{id}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
_LINK = re.compile(r"(?:open\.spotify\.com/(?:intl-[a-z-]+/)?(?:embed/)?|spotify:)(playlist|album|track)[/:]([A-Za-z0-9]{22})")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


class PublicSpotifyError(RuntimeError):
    """Raised when a public Spotify page can't be read."""


def parse_spotify_link(text: str) -> Optional[Tuple[str, str]]:
    """Return (kind, id) for a Spotify playlist, album or track link or URI, or None.

    @param text: A link such as https://open.spotify.com/playlist/<id>?si=... or a spotify: URI.
    """
    match = _LINK.search(text or "")
    return (match.group(1), match.group(2)) if match else None


def _fetch_html(url: str) -> str:
    """Download a page as text.

    @param url: Page URL.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", "replace")


def _artists(subtitle: str) -> str:
    """Turn the embed's artist line into HARMONI's comma-separated artist string.

    @param subtitle: Artist names as the embed shows them, joined with a comma and a non-breaking space.
    """
    names = [n.strip() for n in (subtitle or "").replace(" ", " ").split(",")]
    return ", ".join(n for n in names if n)


def _to_track(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert one embed track entry into a HARMONI track dict, or None when it can't be downloaded.

    @param item: Entry from the embed's trackList.
    """
    title = (item.get("title") or "").strip()
    artist = _artists(item.get("subtitle") or "")
    if not title or not artist or item.get("isPlayable") is False:
        return None
    uri = item.get("uri") or ""
    return {
        "artist": artist,
        "track": title,
        "duration_ms": item.get("duration"),
        "uri": uri,
        "spotify_id": uri.rsplit(":", 1)[-1] if uri.startswith("spotify:track:") else None,
        "explicit": item.get("isExplicit"),
    }


def fetch_public_tracks(kind: str, spotify_id: str, *, fetch: Callable[[str], str] = _fetch_html) -> Tuple[str, List[Dict[str, Any]]]:
    """Return (name, tracks) for a public playlist, album or track.

    Spotify's embed page lists at most 100 tracks of a playlist, so very long playlists come back shortened.

    @param kind: "playlist", "album" or "track".
    @param spotify_id: The 22-character Spotify id.
    @param fetch: Downloads a URL as text, replaceable in tests.
    """
    try:
        html = fetch(EMBED_URL.format(kind=kind, id=spotify_id))
    except OSError as e:
        raise PublicSpotifyError(f"Couldn't reach Spotify: {e}") from e
    match = _NEXT_DATA.search(html)
    try:
        entity = json.loads(match.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise PublicSpotifyError("Spotify didn't return this page. Check the link is public.") from e

    name = entity.get("name") or entity.get("title") or kind.title()
    items = entity.get("trackList") if kind != "track" else [dict(entity, subtitle=_entity_artists(entity))]
    tracks = [t for t in (_to_track(i) for i in items or []) if t]
    return name, tracks


def _entity_artists(entity: Dict[str, Any]) -> str:
    """Return the artist line for a single-track embed, which keeps artists in a separate list.

    @param entity: The track entity from the embed page.
    """
    names = [a.get("name") for a in entity.get("artists") or [] if isinstance(a, dict)]
    return ", ".join(n for n in names if n) or entity.get("subtitle") or ""
