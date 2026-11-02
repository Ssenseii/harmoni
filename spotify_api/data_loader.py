from typing import Any, Callable, Dict, List, Optional

from .client import SpotifyClient


def playlist_total(p: Dict[str, Any]) -> Optional[int]:
    """Return a playlist's item count from the Feb 2026 "items" field, falling back to the legacy "tracks" field.

    @param p: Playlist object from the Spotify Web API.
    """
    for key in ("items", "tracks"):
        field = p.get(key)
        if isinstance(field, dict) and field.get("total") is not None:
            return field.get("total")
    return None


class SpotifyDataLoader:
    """High-level helpers for extracting playlists and tracks from Spotify.

    Normalized track dicts are designed to be compatible with HARMONI's existing
    loader expectations (see utils/loaders.py):
      - required: artist, track
      - recommended: album, uri, release_date, duration_ms, explicit, popularity

    The song selection UI only relies on {artist, track}, so extra metadata is safe.
    """

    def __init__(self, client: SpotifyClient):
        self.client = client
        self._me: Optional[Dict[str, Any]] = None

    def current_user(self) -> Dict[str, Any]:
        """Return the /me profile, fetched once per loader."""
        if self._me is None:
            self._me = self.client.me() or {}
        return self._me

    def _collect_pages(
        self,
        fetch_page: Callable[[int, int], Dict[str, Any]],
        convert: Callable[[Any], Optional[Dict[str, Any]]],
        *,
        limit: int,
        max_items: Optional[int],
        on_batch: Optional[Callable[[List[Dict[str, Any]], int], None]],
        should_cancel: Optional[Callable[[], bool]],
    ) -> List[Dict[str, Any]]:
        """Page through an {items, total} endpoint and return the converted items.

        @param fetch_page: Called with (limit, offset) and returns one page.
        @param convert: Maps one raw entry to a dict, or None to skip it.
        @param limit: Page size.
        @param max_items: Optional cap on the number of converted items.
        @param on_batch: Optional callback given each page's converted items and the total Spotify reports.
        @param should_cancel: Optional callable checked before each page request.
        """
        out: List[Dict[str, Any]] = []
        offset = 0

        while True:
            if max_items is not None and len(out) >= int(max_items):
                break
            if should_cancel is not None and should_cancel():
                break

            page = fetch_page(limit, offset)
            items = page.get("items") or []

            batch: List[Dict[str, Any]] = []
            for raw in items:
                converted = convert(raw)
                if converted:
                    batch.append(converted)
                if max_items is not None and len(out) + len(batch) >= int(max_items):
                    break
            out.extend(batch)
            total = page.get("total")
            if batch and on_batch is not None:
                on_batch(batch, int(total or 0))

            if total is None:
                break

            offset += len(items)
            if offset >= int(total):
                break

            if not items:
                break

        return out

    def list_all_playlists(
        self,
        *,
        limit: int = 50,
        max_playlists: Optional[int] = None,
        on_batch: Optional[Callable[[List[Dict[str, Any]], int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[Dict[str, Any]]:
        """Return the current user's playlists, each marked fetchable when Spotify lets the app read its items.

        @param limit: Page size.
        @param max_playlists: Optional cap on the number of playlists.
        @param on_batch: Optional callback given each page's playlists and the total Spotify reports.
        @param should_cancel: Optional callable checked before each page request.
        """
        me_id = self.current_user().get("id")

        def convert(p: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(p, dict):
                return None
            owner = p.get("owner") if isinstance(p.get("owner"), dict) else {}
            owner_id = owner.get("id")
            collaborative = bool(p.get("collaborative"))
            images = p.get("images") or []
            return {
                "id": p.get("id"),
                "name": p.get("name"),
                "tracks_total": playlist_total(p),
                "owner": owner.get("display_name"),
                "owner_id": owner_id,
                "collaborative": collaborative,
                "fetchable": collaborative or (owner_id is not None and owner_id == me_id),
                "public": p.get("public"),
                "image_url": images[0].get("url") if images and isinstance(images[0], dict) else None,
            }

        return self._collect_pages(
            lambda lim, off: self.client.current_user_playlists(limit=lim, offset=off),
            convert,
            limit=limit,
            max_items=max_playlists,
            on_batch=on_batch,
            should_cancel=should_cancel,
        )

    def _entry_converter(self, field: str) -> Callable[[Any], Optional[Dict[str, Any]]]:
        """Build a converter for {added_at, <field>: track} entries.

        @param field: Key holding the track object, "item" for playlists since Feb 2026 or "track" for liked songs.
        """

        def convert(entry: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(entry, dict):
                return None
            track_obj = entry.get(field)
            if track_obj is None and field == "item":
                track_obj = entry.get("track")
            normalized = self._normalize_track(track_obj)
            if normalized and entry.get("added_at"):
                normalized["added_at"] = entry.get("added_at")
            return normalized

        return convert

    def load_playlist_tracks(
        self,
        playlist_id: str,
        *,
        limit: int = 100,
        max_tracks: Optional[int] = None,
        on_batch: Optional[Callable[[List[Dict[str, Any]], int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[Dict[str, Any]]:
        """Return playlist tracks as dicts suitable for HARMONI workflows, keyed like Exportify CSV where possible.

        @param playlist_id: Spotify playlist id. Spotify only returns items for playlists the user owns or collaborates on.
        @param limit: Page size.
        @param max_tracks: Optional safety cap to stop paging after N normalized tracks.
        @param on_batch: Optional callback given each page's normalized tracks and the total Spotify reports.
        @param should_cancel: Optional callable checked before each page request.
        """
        return self._collect_pages(
            lambda lim, off: self.client.playlist_items(playlist_id, limit=lim, offset=off),
            self._entry_converter("item"),
            limit=limit,
            max_items=max_tracks,
            on_batch=on_batch,
            should_cancel=should_cancel,
        )

    def load_liked_songs(
        self,
        *,
        limit: int = 50,
        max_tracks: Optional[int] = None,
        on_batch: Optional[Callable[[List[Dict[str, Any]], int], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[Dict[str, Any]]:
        """Return the user's saved tracks (Liked Songs).

        @param limit: Page size.
        @param max_tracks: Optional safety cap to stop paging after N normalized tracks.
        @param on_batch: Optional callback given each page's normalized tracks and the total Spotify reports.
        @param should_cancel: Optional callable checked before each page request.
        """
        return self._collect_pages(
            lambda lim, off: self.client.current_user_saved_tracks(limit=lim, offset=off),
            self._entry_converter("track"),
            limit=limit,
            max_items=max_tracks,
            on_batch=on_batch,
            should_cancel=should_cancel,
        )

    def load_user_playlists_with_tracks(
        self,
        *,
        include_liked_songs: bool = False,
        playlist_limit: int = 50,
        track_limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Load the current user's readable playlists and attach normalized track lists.

        Returns a list compatible with load_playlists() output:
          [{"name": str, "tracks": [track_dict, ...]}, ...]

        Playlists Spotify will not let the app read (not owned and not collaborative) are left out.

        @param include_liked_songs: Prepend a pseudo-playlist "Liked Songs".
        @param playlist_limit: Maximum number of playlists to load.
        @param track_limit: Maximum number of tracks per playlist.
        """

        out: List[Dict[str, Any]] = []

        if include_liked_songs:
            liked = self.load_liked_songs(
                limit=min(50, int(track_limit)),
                max_tracks=int(track_limit),
            )
            out.append({"name": "Liked Songs", "tracks": liked})

        playlists = self.list_all_playlists(limit=min(50, int(playlist_limit)), max_playlists=int(playlist_limit))
        for p in playlists:
            pid = (p.get("id") or "").strip() if isinstance(p, dict) else ""
            name = (p.get("name") or "").strip() if isinstance(p, dict) else ""
            if not pid or not name or not p.get("fetchable"):
                continue

            tracks = self.load_playlist_tracks(
                pid,
                limit=min(100, int(track_limit)),
                max_tracks=int(track_limit),
            )
            out.append({"name": name, "tracks": tracks})

        return out

    @staticmethod
    def _normalize_artist_list(artists: Any) -> str:
        if not isinstance(artists, list):
            return ""
        names = []
        for a in artists:
            if isinstance(a, dict) and a.get("name"):
                names.append(str(a.get("name")).strip())
        # Match utils.loaders._normalize_artists output style: comma-separated for multi-artist
        names = [n for n in names if n]
        # de-dupe preserving order
        seen = set()
        uniq = []
        for n in names:
            key = n.casefold()
            if key in seen:
                continue
            seen.add(key)
            uniq.append(n)
        return ", ".join(uniq)

    @classmethod
    def _normalize_track(cls, track_obj: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(track_obj, dict):
            return None

        # Episodes / local tracks may appear depending on playlist.
        if track_obj.get("is_local"):
            return None

        artist_name = cls._normalize_artist_list(track_obj.get("artists"))

        album = track_obj.get("album") or {}
        album_name = album.get("name") if isinstance(album, dict) else None
        release_date = album.get("release_date") if isinstance(album, dict) else None
        
        # Extract album artwork URL (largest available image)
        album_art_url = None
        if isinstance(album, dict):
            images = album.get("images") or []
            if isinstance(images, list) and images:
                # Spotify returns images sorted by size (largest first usually)
                album_art_url = images[0].get("url") if images[0] else None

        uri = track_obj.get("uri")
        spotify_id = track_obj.get("id")

        out: Dict[str, Any] = {
            "artist": artist_name or "",
            "track": (track_obj.get("name") or ""),
            "album": album_name or "",
            "album_art_url": album_art_url,
            "uri": uri,
            "spotify_id": spotify_id,
            "duration_ms": track_obj.get("duration_ms"),
            "explicit": track_obj.get("explicit"),
            "popularity": track_obj.get("popularity"),
            "release_date": release_date,
            "isrc": (
                (track_obj.get("external_ids") or {}).get("isrc")
                if isinstance(track_obj.get("external_ids"), dict)
                else None
            ),
            "external_url": (
                (track_obj.get("external_urls") or {}).get("spotify")
                if isinstance(track_obj.get("external_urls"), dict)
                else None
            ),
        }

        # Strip empties (keep numeric/bool values if present)
        cleaned: Dict[str, Any] = {}
        for k, v in out.items():
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            cleaned[k] = v

        # Must have core identifiers for downstream download workflow.
        if not cleaned.get("artist") or not cleaned.get("track"):
            return None

        return cleaned
