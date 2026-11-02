# Data Formats

This document describes the JSON and CSV formats used by HARMONI.

A fresh clone has no `data/tracks.json` or `data/playlists.json`, because they hold personal data and are not tracked. HARMONI treats a missing file as an empty list. To start one, copy `data/tracks.example.json` to `data/tracks.json` or `data/playlists.example.json` to `data/playlists.json` and edit it.

---

## Track List Format

`data/tracks.json` - Main track list for downloading.

```json
{
  "tracks": [
    {
      "artist": "Artist Name",
      "album": "Album Name",
      "track": "Song Title",
      "uri": "spotify:track:xxxx"
    }
  ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `artist` | Yes | Artist name |
| `album` | No | Album name |
| `track` | Yes | Song title |
| `uri` | No | Spotify track URI |

---

## Playlist Format

`data/playlists.json` - Playlists with nested tracks.

```json
{
  "playlists": [
    {
      "name": "Playlist Name",
      "lastModifiedDate": "2025-05-03",
      "items": [
        {
          "track": {
            "trackName": "Song Title",
            "artistName": "Artist Name",
            "albumName": "Album Name",
            "trackUri": "spotify:track:xxxx"
          },
          "addedDate": "2025-05-03"
        }
      ]
    }
  ]
}
```

This format matches the official Spotify data export structure. A playlist may instead hold a `tracks` list in the flat track list format above.

---

## Exportify CSV Format

Place CSV files from [Exportify](https://exportify.net/) in `data/exportify/`.

Required columns:
- `Artist Name(s)` - Artist name
- `Track Name` - Song title

The filename (without extension) becomes the playlist name.

---

## Generated Files

### Failed Downloads

`data/failed_downloads.json` - Tracks that failed to download.

```json
[
  {
    "artist": "Artist Name",
    "track": "Song Title"
  }
]
```

### Download Progress

`data/download_progress.json` - Saved state for resuming batch downloads.

```json
[
  {
    "artist": "Artist Name",
    "track": "Song Title"
  }
]
```

### Download History

`data/download_history.json` - Successfully downloaded tracks.

```json
[
  {
    "artist": "Artist Name",
    "track": "Song Title",
    "downloaded_at": "2025-01-15T10:30:00"
  }
]
```

---

## Export Files

### Library Export

`export/harmoni_export_YYYY-MM-DD.json` - Inventory of downloaded music.

```json
{
  "music_files": [
    "Artist - Song.mp3",
    "Another Artist - Another Song.mp3"
  ]
}
```

### Playlist Tracklist

`export/playlist_tracklist.json` - Flattened tracklist from playlists.

```json
{
  "tracks": [
    {
      "artist": "Artist Name",
      "album": "Album Name",
      "track": "Song Title",
      "uri": "spotify:track:xxxx"
    }
  ]
}
```

---

## Spotify Tokens

`data/spotify_tokens.json` - Cached OAuth tokens (when enabled).

This file is managed automatically by the Spotify API module.
