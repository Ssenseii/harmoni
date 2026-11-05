# Configuration Reference

All settings are stored in `config.json` at the project root.

## Full Configuration Example

```json
{
  "tracks_file": "data/tracks.json",
  "playlists_file": "data/playlists.json",
  "output_dir": "music",
  "audio_format": "mp3",
  "sleep_between": 5,
  "average_download_time": 20,
  "retry_attempts": 3,
  "retry_delay": 5,
  "auto_cleanup": false,
  "auto_backup": true,
  "max_backups": 10,
  "profile": "light",
  "exportify_watch_folder": "data/exportify",
  "auto_sync_enabled": false,
  "auto_sync_interval": 3600,
  "spotify_client_id": "",
  "spotify_redirect_uri": "http://127.0.0.1:8888/callback",
  "spotify_scopes": [
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read"
  ],
  "spotify_cache_tokens": true,
  "spotify_auto_refresh": true
}
```

---

## Settings Reference

### File Paths

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `tracks_file` | string | `"data/tracks.json"` | Path to tracks JSON file |
| `playlists_file` | string | `"data/playlists.json"` | Path to playlists JSON file |
| `output_dir` | string | `"music"` | Directory for downloaded music |
| `exportify_watch_folder` | string | `"data/exportify"` | Folder for Exportify CSV files |

### Download Settings

| Setting | Type | Default | Range | Description |
|---------|------|---------|-------|-------------|
| `audio_format` | string | `"mp3"` | mp3, wav, flac, aac, ogg, m4a | Default audio format |
| `sleep_between` | int | `5` | 0-60 | Seconds between downloads (rate limiting) |
| `average_download_time` | int | `20` | 1-300 | Estimated time per track (for ETA) |
| `match_duration_tolerance` | int | `15` | 0-120 | Seconds a YouTube result may differ from the track length when the length is known |

### Retry Settings

| Setting | Type | Default | Range | Description |
|---------|------|---------|-------|-------------|
| `retry_attempts` | int | `3` | 0-10 | Retry attempts for failed downloads |
| `retry_delay` | int | `5` | 0-60 | Seconds between retry attempts |

### Automation Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `auto_cleanup` | bool | `false` | Clean up after downloads |
| `auto_backup` | bool | `true` | Backup JSON files automatically |
| `max_backups` | int | `10` | Maximum backups to keep (0-100) |
| `auto_sync_enabled` | bool | `false` | Auto-sync Exportify folder |
| `auto_sync_interval` | int | `3600` | Sync interval in seconds (60-86400) |

### Spotify API Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `spotify_client_id` | string | `""` | Your Spotify Developer app Client ID |
| `spotify_redirect_uri` | string | `"http://127.0.0.1:8888/callback"` | OAuth redirect URI |
| `spotify_scopes` | array | (see above) | Requested permissions |
| `spotify_cache_tokens` | bool | `true` | Cache OAuth tokens |
| `spotify_auto_refresh` | bool | `true` | Auto-refresh expired tokens |
| `spotify_max_retry_after` | int | `30` | Longest wait in seconds when Spotify rate limits a request (1-3600) |

---

## Configuration Profiles

HARMONI includes pre-defined profiles for common use cases:

### Light (Default)
- Minimal retries (1 attempt)
- Quick delays (3s)
- Basic backup (5 max)

### Advanced
- Maximum retries (5 attempts)
- Longer delays (10s)
- Extensive backup (20 max)

### Minimal
- No retries
- No backups
- Fastest settings (2s delay)

Switch profiles via **Config Menu > Switch config profile** in the app.

---

## Managing Configuration

### Via the App

Use the **Config Menu** to:
- View current settings
- Update individual settings
- Switch profiles
- Toggle automation features
- Reset to defaults
- Validate configuration

### Manually

Edit `config.json` directly. Missing fields are automatically filled with defaults on startup.
