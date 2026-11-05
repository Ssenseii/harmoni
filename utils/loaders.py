import os
import csv
from utils.logger import log_info, log_warning, log_error


def _normalize_artists(raw: str) -> str:
    """Normalize Exportify's semicolon-separated Artist Name(s) field to a search-friendly string."""
    raw = (raw or "").strip()
    if not raw:
        return ""

    # Exportify uses semicolons for multi-artist entries, e.g. "A;B;C".
    # Some CSVs may use commas; we only treat commas as delimiters if semicolons are not present.
    delimiter = ";" if ";" in raw else ","
    parts = [p.strip() for p in raw.split(delimiter)]
    parts = [p for p in parts if p]

    if not parts:
        return raw

    # De-dupe while preserving order (some exports can repeat artists).
    seen = set()
    uniq = []
    for p in parts:
        key = p.casefold()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)

    return ", ".join(uniq)


def _extract_csv_metadata(row: dict) -> dict:
    """Extract comprehensive metadata from Exportify CSV row."""
    # Standard fields
    artist_raw = (row.get("Artist Name(s)") or row.get("Artist") or "").strip()
    track_name = (row.get("Track Name") or row.get("Track") or "").strip()
    
    artist = _normalize_artists(artist_raw)
    
    # Extract all available metadata fields from Exportify CSV
    metadata = {
        "artist": artist,
        "track": track_name,
        "album": (row.get("Album Name") or "").strip(),
        "uri": (row.get("Track URI") or "").strip(),
        
        # Extended metadata
        "release_date": (row.get("Release Date") or "").strip(),
        "genres": (row.get("Genres") or "").strip(),
        "record_label": (row.get("Record Label") or "").strip(),
        "duration_ms": (row.get("Duration (ms)") or "").strip(),
        "popularity": (row.get("Popularity") or "").strip(),
        "explicit": (row.get("Explicit") or "").strip(),
        
        # Audio analysis features (if available)
        "danceability": (row.get("Danceability") or "").strip(),
        "energy": (row.get("Energy") or "").strip(),
        "key": (row.get("Key") or "").strip(),
        "loudness": (row.get("Loudness") or "").strip(),
        "mode": (row.get("Mode") or "").strip(),
        "speechiness": (row.get("Speechiness") or "").strip(),
        "acousticness": (row.get("Acousticness") or "").strip(),
        "instrumentalness": (row.get("Instrumentalness") or "").strip(),
        "liveness": (row.get("Liveness") or "").strip(),
        "valence": (row.get("Valence") or "").strip(),
        "tempo": (row.get("Tempo") or "").strip(),
        "time_signature": (row.get("Time Signature") or "").strip(),
    }
    
    # Only include non-empty fields
    return {k: v for k, v in metadata.items() if v}


def _extract_json_metadata(track: dict) -> dict:
    """Extract and normalize metadata from JSON track format."""
    metadata = {
        "artist": (track.get("artist") or "").strip(),
        "track": (track.get("track") or track.get("title") or "").strip(),
        "album": (track.get("album") or "").strip(),
        "uri": (track.get("uri") or "").strip(),
    }
    
    # Add any additional fields from JSON that might be present
    for key in ["release_date", "genres", "record_label", "duration_ms", "popularity"]:
        if key in track and track[key]:
            metadata[key] = str(track[key]).strip()
    
    # Only include non-empty fields
    return {k: v for k, v in metadata.items() if v}


def parse_exportify_csv_for_queue(file_path: str) -> list:
    """Parse an Exportify CSV into flat dicts (track/artist/album/playlist) for queueing.

    This is a lighter-weight variant of load_exportify_tracks(), used by drag-and-drop
    import, which keeps only the primary artist and tags each track with a playlist name.
    """
    tracks = []

    # utf-8-sig strips the BOM Exportify includes and is backwards compatible with
    # plain utf-8 files that have no BOM.
    with open(file_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            track_name = row.get("Track Name") or row.get("track_name") or row.get("name")
            artist_name = row.get("Artist Name(s)") or row.get("artist_name") or row.get("artist")
            album_name = row.get("Album Name") or row.get("album_name") or row.get("album")
            playlist_name = row.get("Playlist Name") or row.get("playlist_name") or os.path.basename(file_path)

            if track_name and artist_name:
                if ";" in artist_name:
                    artist_name = artist_name.split(";")[0].strip()
                elif "," in artist_name:
                    artist_name = artist_name.split(",")[0].strip()

                tracks.append({
                    "track": track_name.strip(),
                    "artist": artist_name.strip(),
                    "album": album_name.strip() if album_name else "",
                    "playlist": playlist_name.replace(".csv", "").strip() if playlist_name else "Import",
                })

    return tracks


def load_exportify_tracks(csv_file: str):
    """Load a single Exportify CSV into a flat list of track dicts with comprehensive metadata."""
    tracks = []

    if not csv_file or not os.path.exists(csv_file):
        log_warning(f"CSV file not found: {csv_file}")
        return tracks

    try:
        # utf-8-sig handles the BOM that Exportify often includes.
        with open(csv_file, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                metadata = _extract_csv_metadata(row)
                
                if not metadata.get("artist") or not metadata.get("track"):
                    continue

                tracks.append(metadata)
    except Exception as e:
        log_error(f"Error reading CSV file {csv_file}: {e}")
        return []

    return tracks


def load_primary_tracks(config: dict):
    """Load tracks based on configured primary input source, falling back to tracks_file."""
    primary = (config or {}).get("primary_input_source", "json")

    if primary == "csv":
        csv_file = (config or {}).get("primary_csv_file")
        if csv_file and os.path.exists(csv_file):
            return load_exportify_tracks(csv_file)

        # Fallback: if no explicit CSV file is set, merge all CSVs in exportify_watch_folder.
        exportify_dir = (config or {}).get("exportify_watch_folder", "data/exportify")
        if exportify_dir and os.path.exists(exportify_dir):
            merged = []
            seen = set()
            for filename in sorted(os.listdir(exportify_dir)):
                if not filename.lower().endswith(".csv"):
                    continue
                for t in load_exportify_tracks(os.path.join(exportify_dir, filename)):
                    # Use canonical key for deduplication
                    key = f"{t.get('artist','').casefold()}|{t.get('track','').casefold()}"
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append(t)
            if merged:
                return merged

    # Fallback: tracks_file can be JSON or CSV.
    return load_tracks((config or {}).get("tracks_file", "data/tracks.json"))


def load_tracks(tracks_file):
    """Load tracks with enhanced metadata extraction."""
    # Allow tracks_file to be a CSV directly (Exportify format)
    if isinstance(tracks_file, str) and tracks_file.lower().endswith(".csv"):
        return load_exportify_tracks(tracks_file)

    if not tracks_file or not os.path.exists(tracks_file):
        log_warning(f"Tracks file not found: {tracks_file}. Copy data/tracks.example.json to start one.")
        return []

    try:
        import json
        with open(tracks_file, "r", encoding="utf-8") as f:
            json_data = json.load(f)
            
        tracks_data = json_data.get("tracks", [])
        if not isinstance(tracks_data, list):
            log_warning(f"Unexpected tracks format in {tracks_file}")
            return []
            
        # Extract metadata from each track
        tracks = []
        for track in tracks_data:
            metadata = _extract_json_metadata(track)
            if metadata.get("artist") and metadata.get("track"):
                tracks.append(metadata)
                
        return tracks
    except Exception as e:
        log_error(f"Error loading tracks file: {e}")
        return []


def _spotify_export_item_to_track(item) -> dict:
    """Map one Spotify data export playlist item to the flat artist/track/album/uri shape.

    @param item: An entry of a playlist's items list, holding a track dict with trackName and artistName.
    """
    t = item.get("track") if isinstance(item, dict) else None
    if not isinstance(t, dict):
        return {}
    return {
        "artist": t.get("artistName") or "",
        "track": t.get("trackName") or "",
        "album": t.get("albumName") or "",
        "uri": t.get("trackUri") or "",
    }


def load_playlists(playlists_file):
    """Load playlists from either the flat tracks shape or the Spotify data export items shape.

    @param playlists_file: Path to the playlists JSON file.
    """
    import json
    if not playlists_file or not os.path.exists(playlists_file):
        log_warning(f"Playlists file not found: {playlists_file}. Copy data/playlists.example.json to start one.")
        return []

    try:
        with open(playlists_file, "r", encoding="utf-8") as f:
            json_data = json.load(f)
            
        playlists_data = json_data.get("playlists", [])
        if not isinstance(playlists_data, list):
            log_warning(f"Unexpected playlists format in {playlists_file}")
            return []
            
        # Enhance playlist tracks with metadata
        enhanced_playlists = []
        for playlist in playlists_data:
            if not isinstance(playlist, dict):
                continue
                
            enhanced_playlist = {
                "name": (playlist.get("name") or "").strip(),
                "tracks": []
            }
            
            tracks = playlist.get("tracks")
            if not isinstance(tracks, list):
                tracks = [_spotify_export_item_to_track(i) for i in playlist.get("items") or []]
            if isinstance(tracks, list):
                for track in tracks:
                    metadata = _extract_json_metadata(track)
                    if metadata.get("artist") and metadata.get("track"):
                        enhanced_playlist["tracks"].append(metadata)
                        
            if enhanced_playlist["tracks"]:
                enhanced_playlists.append(enhanced_playlist)
                
        return enhanced_playlists
    except Exception as e:
        log_error(f"Error loading playlists file: {e}")
        return []


def load_exportify_playlists(exportify_dir="data/exportify"):
    """
    Scans the exportify folder for CSV files and parses them into playlist dicts.
    Each playlist dict includes comprehensive metadata.
    """
    playlists = []
    if not os.path.exists(exportify_dir):
        return playlists

    for file in os.listdir(exportify_dir):
        if not file.lower().endswith(".csv"):
            continue

        playlist_name = os.path.splitext(file)[0]
        playlist_path = os.path.join(exportify_dir, file)

        tracks = []
        try:
            # utf-8-sig handles Exportify BOM
            with open(playlist_path, newline="", encoding="utf-8-sig") as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    metadata = _extract_csv_metadata(row)
                    if metadata.get("artist") and metadata.get("track"):
                        tracks.append(metadata)
        except Exception as e:
            log_error(f"Error reading CSV file {playlist_path}: {e}")
            continue

        if tracks:
            playlists.append({"name": playlist_name, "tracks": tracks})

    return playlists


def enrich_with_musicbrainz(tracks: list, config: dict) -> list:
    """
    Enrich track metadata with MusicBrainz data (no API keys required).
    
    Args:
        tracks: List of track dicts
        config: Config dict containing settings
        
    Returns:
        List of tracks with potentially enriched metadata
    """
    if not config.get("enable_musicbrainz_lookup", True):
        return tracks
        
    try:
        from downloader.metadata import lookup_musicbrainz
    except ImportError:
        log_warning("MusicBrainz lookup not available, skipping enrichment")
        return tracks
        
    enriched_tracks = []
    total = len(tracks)
    
    log_info(f"Enriching {total} tracks with MusicBrainz data...")
    
    for i, track in enumerate(tracks):
        if i % 10 == 0:  # Log progress every 10 tracks
            log_info(f"MusicBrainz enrichment: {i}/{total} tracks processed")
            
        enriched_track = track.copy()
        artist = track.get("artist", "")
        title = track.get("track", "")
        
        # Only enrich if we have basic info and missing album/date
        if artist and title and (not track.get("album") or not track.get("release_date")):
            try:
                mb_match = lookup_musicbrainz(artist, title)
                if mb_match:
                    if not enriched_track.get("album") and mb_match.album:
                        enriched_track["album"] = mb_match.album
                    if not enriched_track.get("release_date") and mb_match.date:
                        enriched_track["release_date"] = mb_match.date
            except Exception as e:
                log_warning(f"MusicBrainz lookup failed for {artist} - {title}: {e}")
                
        enriched_tracks.append(enriched_track)
        
    log_info(f"MusicBrainz enrichment completed: {total}/{total} tracks processed")
    return enriched_tracks
