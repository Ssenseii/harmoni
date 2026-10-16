import os
import json
import time 
import urllib.parse 
import urllib.request 
import socket
import random
from dataclasses import dataclass
from functools import lru_cache 
from typing import Any, Dict, Optional, Tuple

from mutagen import File as MutagenFile 
from mutagen.easyid3 import EasyID3 
from mutagen.id3 import ID3, APIC, ID3NoHeaderError 
from mutagen.flac import FLAC, Picture 
from mutagen.mp4 import MP4, MP4Cover 
from mutagen.oggvorbis import OggVorbis 
from mutagen.oggopus import OggOpus 
from mutagen.aac import AAC 
from mutagen.wave import WAVE

from utils.logger import log_info, log_warning, log_error
from constants import VALID_AUDIO_EXTENSIONS


# -----------------------------
# Templates
# -----------------------------

METADATA_TEMPLATES: Dict[str, Dict[str, Any]] = {
    # Suitable for minimal tagging / broad compatibility.
    "basic": {
        "fields": {
            "artist": True,
            "title": True,
            "album": True,
            "date": False,
            "genre": False,
            "bpm": False,
            "comment": False,
        },
        "embed_cover_art": False,
    },
    # Includes more common tags.
    "comprehensive": {
        "fields": {
            "artist": True,
            "title": True,
            "album": True,
            "date": True,
            "genre": True,
            "bpm": True,
            "comment": True,
        },
        "embed_cover_art": True,
    },
    # DJ-oriented: emphasize BPM/genre/comment (e.g., key, energy) while still keeping core tags.
    "dj-mix": {
        "fields": {
            "artist": True,
            "title": True,
            "album": True,
            "date": True,
            "genre": True,
            "bpm": True,
            "comment": True,
        },
        "embed_cover_art": False,
    },
}


def get_metadata_template(name: Optional[str]) -> Dict[str, Any]:
    if not name:
        return METADATA_TEMPLATES["basic"]
    return METADATA_TEMPLATES.get(name, METADATA_TEMPLATES["basic"])


# -----------------------------
# Normalization + validation
# -----------------------------


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        # Commonly genres are lists
        return ", ".join([str(x).strip() for x in v if str(x).strip()])
    return str(v).strip()


def canonical_track_key(artist: str, title: str) -> str:
    return f"{(artist or '').casefold()}|{(title or '').casefold()}"


def normalize_track_metadata(track: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a track dict into a canonical metadata dict used by embedders.

    Expected input (best effort):
      - artist, track/title, album, uri
      - from Exportify: Artist Name(s), Track Name, Album Name, Release Date, Genres, Record Label, Tempo, Key, Energy, etc.

    Returns keys:
      artist, title, album, albumartist, tracknumber, discnumber,
      date, genre, bpm, comment, uri, extra
    """
    # Handle both JSON format (artist, track) and CSV format (Artist Name(s), Track Name)
    artist_raw = _as_str(
        track.get("artist") or 
        track.get("Artist Name(s)") or 
        track.get("Artist")
    )
    title = _as_str(
        track.get("track") or 
        track.get("title") or 
        track.get("Track Name") or 
        track.get("Track")
    )
    album = _as_str(
        track.get("album") or 
        track.get("Album Name")
    )
    uri = _as_str(track.get("uri") or track.get("Track URI"))

    # Release position (from the Spotify loaders; Exportify CSVs don't carry it).
    albumartist = _as_str(track.get("album_artist") or track.get("albumartist"))
    tracknumber = _as_str(track.get("track_number"))
    if tracknumber and _as_str(track.get("total_tracks")):
        tracknumber = f"{tracknumber}/{_as_str(track.get('total_tracks'))}"
    discnumber = _as_str(track.get("disc_number"))

    # Normalize multi-artist entries (convert semicolons to commas for search-friendly format)
    artist = artist_raw
    if ";" in artist:
        artists = [a.strip() for a in artist.split(";") if a.strip()]
        artist = ", ".join(artists)

    # CSV fields (our loaders add snake_case) and/or raw CSV keys.
    date = _as_str(track.get("release_date") or track.get("Release Date"))
    genre_raw = track.get("genres") or track.get("Genres") or ""
    genre = _as_str(genre_raw)
    
    # Normalize multi-genre entries (convert semicolons to commas)
    if ";" in genre:
        genres = [g.strip() for g in genre.split(";") if g.strip()]
        genre = ", ".join(genres)

    bpm = track.get("tempo") or track.get("Tempo")
    bpm_str = ""
    if bpm is not None and bpm != "":
        try:
            # Use standard mathematical rounding for BPM
            bpm_str = str(int(float(bpm) + 0.5))
        except Exception:
            bpm_str = _as_str(bpm)

    # Create a compact, useful comment that carries provenance.
    comment_parts = []
    if uri:
        comment_parts.append(f"spotify_uri={uri}")
    if _as_str(track.get("record_label") or track.get("Record Label")):
        comment_parts.append(f"label={_as_str(track.get('record_label') or track.get('Record Label'))}")
    if _as_str(track.get("key") or track.get("Key")):
        comment_parts.append(f"key={_as_str(track.get('key') or track.get('Key'))}")
    if _as_str(track.get("energy") or track.get("Energy")):
        comment_parts.append(f"energy={_as_str(track.get('energy') or track.get('Energy'))}")

    out: Dict[str, Any] = {
        "artist": artist,
        "title": title,
        "album": album,
        "albumartist": albumartist,
        "tracknumber": tracknumber,
        "discnumber": discnumber,
        "date": date,
        "genre": genre,
        "bpm": bpm_str,
        "comment": "; ".join(comment_parts),
        "uri": uri,
        "album_art_url": _as_str(track.get("album_art_url")),  # Pass through album art URL
        "extra": {},
    }

    # Preserve additional Exportify-style fields for validation/correction tools.
    for k in [
        "duration_ms",
        "explicit",
        "popularity",
        "danceability",
        "acousticness",
        "instrumentalness",
        "liveness",
        "valence",
        "time_signature",
    ]:
        if k in track and track[k] not in (None, ""):
            out["extra"][k] = track[k]

    return out


def validate_metadata(metadata: Dict[str, Any]) -> list[str]:
    """Return a list of validation problems (empty list means OK)."""
    issues = []

    if not _as_str(metadata.get("artist")):
        issues.append("missing_artist")
    if not _as_str(metadata.get("title")):
        issues.append("missing_title")

    # BPM sanity
    bpm = _as_str(metadata.get("bpm"))
    if bpm:
        try:
            bpm_int = int(float(bpm))
            if bpm_int <= 0 or bpm_int > 300:
                issues.append("bpm_out_of_range")
        except Exception:
            issues.append("bpm_not_numeric")

    # Date sanity (very light)
    date = _as_str(metadata.get("date"))
    if date and len(date) < 4:
        issues.append("date_too_short")

    return issues


def correct_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort correction for common problems; never raises."""
    fixed = dict(metadata or {})

    # Coerce keys.
    fixed["artist"] = _as_str(fixed.get("artist"))
    fixed["title"] = _as_str(fixed.get("title"))
    fixed["album"] = _as_str(fixed.get("album"))
    fixed["genre"] = _as_str(fixed.get("genre"))
    fixed["date"] = _as_str(fixed.get("date"))
    fixed["comment"] = _as_str(fixed.get("comment"))

    bpm = _as_str(fixed.get("bpm"))
    if bpm:
        try:
            fixed["bpm"] = str(int(round(float(bpm))))
        except Exception:
            # leave original string
            pass

    # Strip empty album rather than tagging blank values.
    if not fixed.get("album"):
        fixed.pop("album", None)

    return fixed


def apply_template(metadata: Dict[str, Any], template_name: Optional[str]) -> Dict[str, Any]:
    tpl = get_metadata_template(template_name)
    fields = (tpl.get("fields") or {})

    # Always carry required fields if present.
    out = {}
    for key in ["artist", "title"]:
        if _as_str(metadata.get(key)):
            out[key] = _as_str(metadata.get(key))

    for key in ["album", "date", "genre", "bpm", "comment"]:
        if fields.get(key) and _as_str(metadata.get(key)):
            out[key] = _as_str(metadata.get(key))

    # Release identity tags are written whenever known, regardless of template:
    # without them taggers like beets can't group tracks into one release.
    for key in ["albumartist", "tracknumber", "discnumber"]:
        if _as_str(metadata.get(key)):
            out[key] = _as_str(metadata.get(key))

    # pass-through for cover art decisions and provenance
    out["uri"] = _as_str(metadata.get("uri"))
    out["album_art_url"] = _as_str(metadata.get("album_art_url"))  # Preserve album art URL
    out["extra"] = metadata.get("extra") or {}

    return out


# -----------------------------
# MusicBrainz (no API keys)
# -----------------------------


MB_BASE = "https://musicbrainz.org/ws/2"
MB_USER_AGENT = "HARMONI/1.0 ( https://github.com/ ; metadata )"
MB_RATE_LIMIT_SECONDS = 1.05  # MusicBrainz asks for 1 req/sec


@dataclass(frozen=True)
class MusicBrainzMatch:
    recording_mbid: str
    release_mbid: Optional[str]
    title: str
    artist: str
    album: Optional[str]
    date: Optional[str]


_last_mb_request_at = 0.0


def _mb_get_json(url: str, timeout: int = 15, max_retries: int = 3, base_delay: float = 0.75) -> Optional[Dict[str, Any]]:
    """Enhanced MusicBrainz request with retry logic and exponential backoff.
    
    Args:
        url: The URL to request
        timeout: Request timeout in seconds
        max_retries: Maximum number of retry attempts
        base_delay: Base delay for exponential backoff (seconds)
    
    Returns:
        Parsed JSON data or None if all attempts fail
    """
    global _last_mb_request_at
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            # Rate limiting - ensure we don't exceed MusicBrainz limits
            now = time.time()
            wait = MB_RATE_LIMIT_SECONDS - (now - _last_mb_request_at)
            if wait > 0:
                time.sleep(wait)
            
            # Create request with proper headers
            req = urllib.request.Request(
                url, 
                headers={
                    "User-Agent": MB_USER_AGENT,
                    "Accept": "application/json",
                }
            )
            
            # Make the request with timeout
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                data = json.loads(raw.decode("utf-8"))
            
            _last_mb_request_at = time.time()
            return data
            
        except (urllib.error.URLError, socket.error, ConnectionResetError) as e:
            last_error = e
            error_type = type(e).__name__
            
            # Log detailed information about the failure
            if attempt < max_retries:
                # Calculate exponential backoff with jitter
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.2 * base_delay)
                log_warning(f"MusicBrainz request failed (attempt {attempt + 1}/{max_retries + 1}): {error_type}: {e}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                log_warning(f"MusicBrainz request failed after {max_retries + 1} attempts: {error_type}: {e}")
                
        except urllib.error.HTTPError as e:
            last_error = e
            # Handle HTTP errors (4xx, 5xx)
            if e.code >= 500 and attempt < max_retries:
                # Server errors - retry with exponential backoff
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.2 * base_delay)
                log_warning(f"MusicBrainz server error {e.code} (attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
            elif e.code == 429 and attempt < max_retries:
                # Rate limit - longer delay
                delay = base_delay * (2 ** attempt) + random.uniform(1.0, 2.0)
                log_warning(f"MusicBrainz rate limit hit (attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                # Client errors (4xx) or exhausted retries - don't retry
                if e.code == 404:
                    log_warning(f"MusicBrainz resource not found: {e}")
                else:
                    log_warning(f"MusicBrainz HTTP error {e.code}: {e}")
                break
                
        except json.JSONDecodeError as e:
            last_error = e
            log_warning(f"MusicBrainz response parsing failed (attempt {attempt + 1}/{max_retries + 1}): {e}")
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
                
        except Exception as e:
            last_error = e
            log_warning(f"MusicBrainz request failed with unexpected error (attempt {attempt + 1}/{max_retries + 1}): {type(e).__name__}: {e}")
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
    
    # All attempts failed
    return None


@lru_cache(maxsize=512)
def lookup_musicbrainz(artist: str, title: str) -> Optional[MusicBrainzMatch]:
    """Best-effort MusicBrainz lookup without credentials.

    Returns a lightweight match containing candidate album/date.
    """
    artist_q = (artist or "").strip()
    title_q = (title or "").strip()
    if not artist_q or not title_q:
        return None

    # Properly escape quotes in the search query
    artist_escaped = artist_q.replace('"', '\\"')
    title_escaped = title_q.replace('"', '\\"')
    query = f'artist:"{artist_escaped}" AND recording:"{title_escaped}"'
    params = urllib.parse.urlencode(
        {
            "query": query,
            "fmt": "json",
            "limit": 1,
        }
    )

    url = f"{MB_BASE}/recording/?{params}"
    
    # Use default retry settings since config is not available in cached function
    data = _mb_get_json(url, timeout=15, max_retries=3, base_delay=0.75)
    if not data:
        return None

    recs = data.get("recordings") or []
    if not recs:
        return None

    rec = recs[0]
    rec_id = rec.get("id")
    rec_title = _as_str(rec.get("title"))

    # artist credit can be complex; take the joined string.
    artist_credit = rec.get("artist-credit") or []
    artist_name = "".join([_as_str(a.get("name") or a.get("artist", {}).get("name") or a.get("joinphrase")) for a in artist_credit])
    artist_name = artist_name or artist_q

    release_mbid = None
    release_title = None
    release_date = None
    releases = rec.get("releases") or []
    if releases:
        rel = releases[0]
        release_mbid = rel.get("id")
        release_title = _as_str(rel.get("title"))
        release_date = _as_str(rel.get("date"))

    if not rec_id:
        return None

    return MusicBrainzMatch(
        recording_mbid=rec_id,
        release_mbid=release_mbid,
        title=rec_title or title_q,
        artist=artist_name,
        album=release_title,
        date=release_date,
    )


def lookup_musicbrainz_with_config(artist: str, title: str, config: Dict[str, Any]) -> Optional[MusicBrainzMatch]:
    """Enhanced MusicBrainz lookup with config-based retry settings."""
    artist_q = (artist or "").strip()
    title_q = (title or "").strip()
    if not artist_q or not title_q:
        return None

    # Properly escape quotes in the search query
    artist_escaped = artist_q.replace('"', '\\"')
    title_escaped = title_q.replace('"', '\\"')
    query = f'artist:"{artist_escaped}" AND recording:"{title_escaped}"'
    params = urllib.parse.urlencode(
        {
            "query": query,
            "fmt": "json",
            "limit": 1,
        }
    )

    url = f"{MB_BASE}/recording/?{params}"
    
    # Get retry settings from config (with defaults)
    max_retries = config.get("musicbrainz_retries", 3)
    base_delay = config.get("musicbrainz_backoff_base", 0.75)
    timeout = config.get("musicbrainz_timeout", 15)
    
    data = _mb_get_json(url, timeout=timeout, max_retries=max_retries, base_delay=base_delay)
    if not data:
        return None

    recs = data.get("recordings") or []
    if not recs:
        return None

    rec = recs[0]
    rec_id = rec.get("id")
    rec_title = _as_str(rec.get("title"))

    # artist credit can be complex; take the joined string.
    artist_credit = rec.get("artist-credit") or []
    artist_name = "".join([_as_str(a.get("name") or a.get("artist", {}).get("name") or a.get("joinphrase")) for a in artist_credit])
    artist_name = artist_name or artist_q

    release_mbid = None
    release_title = None
    release_date = None
    releases = rec.get("releases") or []
    if releases:
        rel = releases[0]
        release_mbid = rel.get("id")
        release_title = _as_str(rel.get("title"))
        release_date = _as_str(rel.get("date"))

    if not rec_id:
        return None

    return MusicBrainzMatch(
        recording_mbid=rec_id,
        release_mbid=release_mbid,
        title=rec_title or title_q,
        artist=artist_name,
        album=release_title,
        date=release_date,
    )


# -----------------------------
# Album art helpers
# -----------------------------


def _find_local_album_art(audio_path: str) -> Optional[bytes]:
    """Return bytes for a sibling .jpg/.jpeg/.png if present."""
    base = os.path.splitext(audio_path)[0]
    for ext in [".jpg", ".jpeg", ".png"]:
        img_path = base + ext
        if os.path.exists(img_path):
            try:
                with open(img_path, "rb") as f:
                    return f.read()
            except Exception as e:
                log_warning(f"Failed reading album art {img_path}: {e}")
                return None
    return None


def _download_album_art(url: str, timeout: int = 10) -> Optional[bytes]:
    """Download album art from URL."""
    if not url:
        return None
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": MB_USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        log_warning(f"Failed downloading album art from {url}: {e}")
        return None


def _guess_mime(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG"):
        return "image/png"
    return "image/jpeg"


# -----------------------------
# Embedding (multi-format)
# -----------------------------


def _set_tags_generic(mut: Any, tags: Dict[str, str]) -> None:
    """Generic tag setter for Vorbis/FLAC-like mapping tags."""
    for k, v in tags.items():
        if not v:
            continue
        try:
            mut[k] = [v]
        except Exception:
            # Some mutagen types want strings not lists.
            try:
                mut[k] = v
            except Exception:
                pass


def _parse_position(value: str) -> Optional[Tuple[int, int]]:
    """Parse "3" or "3/12" into an MP4 (number, total) tuple; total 0 = unknown."""
    num, _, total = (value or "").partition("/")
    try:
        return int(num), int(total or 0)
    except ValueError:
        return None


def _embed_mp3(path: str, tags: Dict[str, str], cover_bytes: Optional[bytes], cover_mime: Optional[str]) -> None:
    # Ensure ID3 header exists
    try:
        EasyID3(path)
    except Exception:
        try:
            audio_id3 = ID3()
            audio_id3.save(path)
        except Exception:
            pass

    # Use EasyID3 for simple tags
    audio = EasyID3(path)
    if tags.get("artist"):
        audio["artist"] = tags["artist"]
    if tags.get("title"):
        audio["title"] = tags["title"]
    if tags.get("album"):
        audio["album"] = tags["album"]
    for key in ("albumartist", "tracknumber", "discnumber"):
        if tags.get(key):
            audio[key] = tags[key]
    if tags.get("date"):
        audio["date"] = tags["date"]
    if tags.get("genre"):
        audio["genre"] = tags["genre"]
    if tags.get("bpm"):
        audio["bpm"] = tags["bpm"]
    audio.save(path)

    # Use raw ID3 for comment and cover art (EasyID3 doesn't support them properly)
    try:
        from mutagen.id3 import COMM
        id3 = ID3(path)
        
        # Add comment if provided
        if tags.get("comment"):
            id3["COMM"] = COMM(encoding=3, lang='eng', desc='', text=tags["comment"])
        
        # Add cover art if provided
        if cover_bytes:
            id3["APIC"] = APIC(
                encoding=3,
                mime=cover_mime or "image/jpeg",
                type=3,
                desc="Cover",
                data=cover_bytes,
            )
        
        id3.save(path)
    except Exception:
        # Not fatal if comment/cover fails
        pass


def _embed_flac(path: str, tags: Dict[str, str], cover_bytes: Optional[bytes], cover_mime: Optional[str]) -> None:
    audio = FLAC(path)
    _set_tags_generic(
        audio,
        {
            "artist": tags.get("artist", ""),
            "title": tags.get("title", ""),
            "album": tags.get("album", ""),
            "albumartist": tags.get("albumartist", ""),
            "tracknumber": tags.get("tracknumber", ""),
            "discnumber": tags.get("discnumber", ""),
            "date": tags.get("date", ""),
            "genre": tags.get("genre", ""),
            "bpm": tags.get("bpm", ""),
            "comment": tags.get("comment", ""),
        },
    )

    if cover_bytes:
        pic = Picture()
        pic.type = 3
        pic.mime = cover_mime or "image/jpeg"
        pic.desc = "Cover"
        pic.data = cover_bytes
        audio.clear_pictures()
        audio.add_picture(pic)

    audio.save()


def _embed_vorbis(path: str, tags: Dict[str, str], cover_bytes: Optional[bytes], _cover_mime: Optional[str]) -> None:
    # Note: embedding cover art in OGG/Vorbis is possible via METADATA_BLOCK_PICTURE,
    # but not all players support it consistently. We default to *not* embedding.
    audio = OggVorbis(path)
    _set_tags_generic(
        audio,
        {
            "artist": tags.get("artist", ""),
            "title": tags.get("title", ""),
            "album": tags.get("album", ""),
            "albumartist": tags.get("albumartist", ""),
            "tracknumber": tags.get("tracknumber", ""),
            "discnumber": tags.get("discnumber", ""),
            "date": tags.get("date", ""),
            "genre": tags.get("genre", ""),
            "bpm": tags.get("bpm", ""),
            "comment": tags.get("comment", ""),
        },
    )
    audio.save()


def _embed_opus(path: str, tags: Dict[str, str], cover_bytes: Optional[bytes], _cover_mime: Optional[str]) -> None:
    audio = OggOpus(path)
    _set_tags_generic(
        audio,
        {
            "artist": tags.get("artist", ""),
            "title": tags.get("title", ""),
            "album": tags.get("album", ""),
            "albumartist": tags.get("albumartist", ""),
            "tracknumber": tags.get("tracknumber", ""),
            "discnumber": tags.get("discnumber", ""),
            "date": tags.get("date", ""),
            "genre": tags.get("genre", ""),
            "bpm": tags.get("bpm", ""),
            "comment": tags.get("comment", ""),
        },
    )
    audio.save()


def _embed_m4a(path: str, tags: Dict[str, str], cover_bytes: Optional[bytes], cover_mime: Optional[str]) -> None:
    audio = MP4(path)
    if tags.get("artist"):
        audio["\xa9ART"] = [tags["artist"]]
    if tags.get("title"):
        audio["\xa9nam"] = [tags["title"]]
    if tags.get("album"):
        audio["\xa9alb"] = [tags["album"]]
    if tags.get("albumartist"):
        audio["aART"] = [tags["albumartist"]]
    for key, atom in (("tracknumber", "trkn"), ("discnumber", "disk")):
        pos = _parse_position(tags.get(key, ""))
        if pos:
            audio[atom] = [pos]
    if tags.get("date"):
        audio["\xa9day"] = [tags["date"]]
    if tags.get("genre"):
        audio["\xa9gen"] = [tags["genre"]]
    if tags.get("bpm"):
        try:
            audio["tmpo"] = [int(float(tags["bpm"]))]
        except Exception:
            pass
    if tags.get("comment"):
        audio["\xa9cmt"] = [tags["comment"]]

    if cover_bytes:
        fmt = MP4Cover.FORMAT_PNG if (cover_mime == "image/png") else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(cover_bytes, imageformat=fmt)]

    audio.save()


def _embed_aac(path: str, tags: Dict[str, str], _cover_bytes: Optional[bytes], _cover_mime: Optional[str]) -> None:
    # AAC (ADTS) metadata support is limited; mutagen can store tags in some containers.
    audio = AAC(path)
    # AAC tags are generally not as portable; set what we can.
    _set_tags_generic(
        audio,
        {
            "artist": tags.get("artist", ""),
            "title": tags.get("title", ""),
            "album": tags.get("album", ""),
            "albumartist": tags.get("albumartist", ""),
            "tracknumber": tags.get("tracknumber", ""),
            "discnumber": tags.get("discnumber", ""),
            "date": tags.get("date", ""),
            "genre": tags.get("genre", ""),
            "comment": tags.get("comment", ""),
        },
    )
    audio.save()


def _embed_wav(path: str, tags: Dict[str, str], cover_bytes: Optional[bytes], cover_mime: Optional[str]) -> None:
    # WAV tagging is inconsistent across players. Mutagen supports ID3-in-WAVE.
    audio = WAVE(path)
    try:
        if audio.tags is None:
            audio.add_tags()
    except Exception:
        # As a fallback, try raw ID3.
        pass

    try:
        id3 = audio.tags
        if id3 is None:
            id3 = ID3()

        if tags.get("artist"):
            id3["TPE1"] = id3.get("TPE1") or None
        # Use EasyID3-style path where possible
        try:
            easy = EasyID3(path)
            if tags.get("artist"):
                easy["artist"] = tags["artist"]
            if tags.get("title"):
                easy["title"] = tags["title"]
            if tags.get("album"):
                easy["album"] = tags["album"]
            for key in ("albumartist", "tracknumber", "discnumber"):
                if tags.get(key):
                    easy[key] = tags[key]
            if tags.get("date"):
                easy["date"] = tags["date"]
            if tags.get("genre"):
                easy["genre"] = tags["genre"]
            if tags.get("bpm"):
                easy["bpm"] = tags["bpm"]
            easy.save(path)
            
            # Add comment using raw ID3
            if tags.get("comment"):
                from mutagen.id3 import COMM
                id3 = ID3(path)
                id3["COMM"] = COMM(encoding=3, lang='eng', desc='', text=tags["comment"])
                id3.save(path)
        except Exception:
            # If EasyID3 doesn't work, do nothing further.
            pass

        if cover_bytes:
            try:
                id3 = ID3(path)
            except Exception:
                id3 = ID3()
            id3["APIC"] = APIC(
                encoding=3,
                mime=cover_mime or "image/jpeg",
                type=3,
                desc="Cover",
                data=cover_bytes,
            )
            id3.save(path)
    except Exception:
        # Not fatal
        pass


def embed_track_metadata(
    audio_path: str,
    track: Dict[str, Any],
    *,
    template: Optional[str] = None,
    allow_musicbrainz: bool = True,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Embed metadata into a single audio file.

    - Uses JSON/CSV-provided metadata first.
    - Optionally enriches with MusicBrainz if album/date are missing.
    - Uses a template to decide which tags to write.

    Returns True on success, False on failure.
    """
    if not audio_path or not os.path.exists(audio_path):
        log_warning(f"Metadata skip: file not found: {audio_path}")
        return False

    ext = os.path.splitext(audio_path)[1].lower()
    if ext not in VALID_AUDIO_EXTENSIONS:
        log_warning(f"Metadata skip: unsupported extension {ext}: {audio_path}")
        return False

    base_meta = normalize_track_metadata(track)
    base_meta = correct_metadata(base_meta)

    if allow_musicbrainz:
        # Only do network lookup if we have core identifiers and are missing album/date.
        need_album = not _as_str(base_meta.get("album"))
        need_date = not _as_str(base_meta.get("date"))
        if (need_album or need_date) and _as_str(base_meta.get("artist")) and _as_str(base_meta.get("title")):
            try:
                # Use config-aware lookup if config is provided, otherwise use cached version
                if config:
                    mb = lookup_musicbrainz_with_config(base_meta["artist"], base_meta["title"], config)
                else:
                    mb = lookup_musicbrainz(base_meta["artist"], base_meta["title"])
                
                if mb:
                    if need_album and mb.album:
                        base_meta["album"] = mb.album
                    if need_date and mb.date:
                        base_meta["date"] = mb.date
            except Exception as e:
                log_warning(f"MusicBrainz lookup failed for {base_meta.get('artist')} - {base_meta.get('title')}: {e}")

    meta = apply_template(base_meta, template)
    issues = validate_metadata(meta)
    if issues:
        log_warning(f"Metadata validation issues for {audio_path}: {issues}")

    tags = {
        "artist": _as_str(meta.get("artist")),
        "title": _as_str(meta.get("title")),
        "album": _as_str(meta.get("album")),
        "albumartist": _as_str(meta.get("albumartist")),
        "tracknumber": _as_str(meta.get("tracknumber")),
        "discnumber": _as_str(meta.get("discnumber")),
        "date": _as_str(meta.get("date")),
        "genre": _as_str(meta.get("genre")),
        "bpm": _as_str(meta.get("bpm")),
        "comment": _as_str(meta.get("comment")),
    }

    tpl = get_metadata_template(template)
    cover_bytes = None
    cover_mime = None
    if tpl.get("embed_cover_art"):
        log_info(f"Checking for album art for {os.path.basename(audio_path)}")
        
        # Try local file first
        cover_bytes = _find_local_album_art(audio_path)
        if cover_bytes:
            log_info(f"  Found local album art ({len(cover_bytes)} bytes)")
        
        # If no local file, try downloading from Spotify
        if not cover_bytes and meta.get("album_art_url"):
            log_info(f"  Downloading album art from Spotify...")
            cover_bytes = _download_album_art(meta.get("album_art_url"))
            if cover_bytes:
                log_info(f"  Downloaded album art ({len(cover_bytes)} bytes)")
        
        if cover_bytes:
            cover_mime = _guess_mime(cover_bytes)
        else:
            log_warning(f"  No album art available")

    try:
        if ext == ".mp3":
            _embed_mp3(audio_path, tags, cover_bytes, cover_mime)
        elif ext == ".flac":
            _embed_flac(audio_path, tags, cover_bytes, cover_mime)
        elif ext == ".ogg":
            # Prefer trying Vorbis first; if it's Opus, fall back.
            try:
                _embed_vorbis(audio_path, tags, cover_bytes, cover_mime)
            except Exception:
                _embed_opus(audio_path, tags, cover_bytes, cover_mime)
        elif ext == ".m4a":
            _embed_m4a(audio_path, tags, cover_bytes, cover_mime)
        elif ext == ".aac":
            _embed_aac(audio_path, tags, cover_bytes, cover_mime)
        elif ext == ".wav":
            _embed_wav(audio_path, tags, cover_bytes, cover_mime)
        else:
            # Best-effort fallback using mutagen's generic loader.
            mut = MutagenFile(audio_path)
            if mut is None:
                raise ValueError("mutagen could not open file")
            if mut.tags is None:
                try:
                    mut.add_tags()
                except Exception:
                    pass
            _set_tags_generic(mut, {k: v for k, v in tags.items() if v})
            mut.save()

        log_info(f"Metadata embedded: {os.path.basename(audio_path)}")
        return True
    except Exception as e:
        log_error(f"Failed to embed metadata for {audio_path}: {e}")
        return False


def find_downloaded_audio_path(output_dir: str, base_filename: str) -> Optional[str]:
    """Given output_dir and a base filename (without extension), find the created audio file."""
    if not output_dir or not base_filename:
        return None

    for ext in sorted(VALID_AUDIO_EXTENSIONS):
        candidate = os.path.join(output_dir, base_filename + ext)
        if os.path.exists(candidate):
            return candidate

    # Fall back to a normalized comparison
    # that ignores punctuation/whitespace differences entirely.
    from utils.filename_match import normalize_match_key

    target_key = normalize_match_key(base_filename)
    try:
        for name in os.listdir(output_dir):
            stem, ext = os.path.splitext(name)
            if ext.lower() not in VALID_AUDIO_EXTENSIONS:
                continue
            if normalize_match_key(stem) == target_key:
                return os.path.join(output_dir, name)
    except Exception:
        pass

    return None


def embed_metadata(output_dir: str) -> None:
    """Legacy batch embed function: walk output_dir and tag all supported audio files by filename parsing."""
    try:
        for root, _, files in os.walk(output_dir):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext not in VALID_AUDIO_EXTENSIONS:
                    continue

                filepath = os.path.join(root, file)

                # Extract artist/title from filename format: Artist - Title.ext
                try:
                    artist, title_ext = file.split(" - ", 1)
                    title = title_ext.rsplit(".", 1)[0]
                except Exception:
                    log_error(f"Skipping {file}: Cannot parse artist/title")
                    continue

                embed_track_metadata(
                    filepath,
                    {"artist": artist.strip(), "track": title.strip()},
                    template="basic",
                    allow_musicbrainz=False,
                )

    except Exception as e:
        log_error(f"Error in embed_metadata: {e}")
