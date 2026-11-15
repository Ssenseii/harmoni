# GUI Guide

HARMONI includes a modern desktop GUI application built with PySide6. This guide covers all features of the graphical interface.

## Launching the GUI

**From Python:**
```bash
python gui_main.py
```

**From executable:**
```bash
./HARMONI.exe     # Windows
./HARMONI         # Linux/macOS
```

---

## Home Screen

![Home Screen](../images/gui_main.png)

The home screen provides the easiest way to get started with HARMONI using Exportify.

### Using Exportify (Recommended)

Exportify is a free website that exports your Spotify playlists to CSV files. This is the simplest method - no Spotify API setup required.

**Steps:**

1. **Go to exportify.net** - Open your web browser and visit [exportify.net](https://exportify.net)
2. **Log in with Spotify** - Click the green button to connect your Spotify account
3. **Export your playlist** - Click "Export" next to any playlist to download a CSV file
4. **Drag and drop** - Drag the CSV file into HARMONI or click the drop zone to browse

HARMONI will automatically parse the CSV and queue all tracks for download.

---

## YouTube Tab

![YouTube Tab](../images/gui_youtube.png)

Download music directly from YouTube by URL or search query.

### Single Track Download

1. Enter a YouTube URL or search query (e.g., "Artist - Song Name")
2. Click **Add to Queue**
3. The track will be added to the download queue

### Batch Download

1. Enter multiple search queries, one per line
2. Format: `Artist - Track Name`
3. Click **Add All to Queue**

**Tips:**
- For best results, use the format: `Artist - Track Name`
- YouTube URLs are also supported (paste the full URL)
- The search will find the first matching result on YouTube

---

## Downloads Tab

![Downloads Tab](../images/gui_downloads.png)

Monitor and manage your download queue.

### Queue Statistics

The top-right shows:
- **Pending** - Tracks waiting to download
- **Completed** - Successfully downloaded tracks
- **Failed** - Tracks that couldn't be downloaded

### Controls

| Button | Action |
|--------|--------|
| **Start Downloads** | Begin processing the queue |
| **Pause** | Pause downloads (can resume) |
| **Cancel** | Stop all downloads |
| **Retry Failed** | Re-attempt failed downloads |
| **Clear Done** | Remove completed items from list |
| **Clear All** | Clear the entire queue |

### Download Status

Each track shows:
- **Artist** - Track artist
- **Track** - Song name
- **Source** - Playlist or source name
- **Status** - Pending, Downloading, Completed, or Failed
- **Progress** - Download progress bar

---

## Settings Tab

![Settings Tab](../images/gui_settings.png)

Configure HARMONI to your preferences.

### FFmpeg Status

Shows whether FFmpeg is installed and its location. FFmpeg is required for audio conversion.

- **Installed** - Shows the FFmpeg path
- **Not Found** - Click "Install FFmpeg" to download automatically

### Output Settings

| Setting | Description |
|---------|-------------|
| **Output Directory** | Where downloaded music is saved |
| **Audio Format** | Output format (mp3, m4a, opus, flac, wav) |

### Spotify Settings

For direct Spotify API access (optional):

| Setting | Description |
|---------|-------------|
| **Client ID** | Your Spotify app client ID |
| **Redirect URI** | OAuth callback URL (default: `http://127.0.0.1:8888/callback`) |

**Getting a Spotify Client ID:**
1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Add `http://127.0.0.1:8888/callback` to Redirect URIs
4. Copy the Client ID

### Download Settings

| Setting | Description |
|---------|-------------|
| **Sleep Between (sec)** | Delay between downloads to avoid rate limiting |
| **Retry Attempts** | Number of times to retry failed downloads |

---

## Spotify Tab

Connect directly to Spotify to browse your playlists and liked songs.

### Connecting to Spotify

1. Enter your Spotify Client ID in Settings
2. Go to the Spotify tab
3. Click **Connect to Spotify**
4. Complete the OAuth flow in your browser

### Browsing Your Library

Once connected:
- View all your playlists
- Browse your liked songs
- Select tracks to download

> Spotify only lets this app read tracks from playlists you own or collaborate on. Playlists you merely follow can't be loaded; export those with [Exportify](https://exportify.net) instead.

### Searching for Albums

Type in the **Search albums...** box above the playlist list and press Enter. The list switches to the top 10 matching albums (Spotify's maximum per search), shown as `Artist - Album (N tracks)`. Albums work exactly like playlists: double-click or **Load** to see their tracks, or **Download** to queue the whole album. Click **My Playlists** to go back to your library.

---

## Status Bar

The bottom status bar shows:
- **Ready/Downloading** - Current application state
- **Queue count** - Number of items in download queue
- **Spotify status** - Connection status (Connected/Not connected)

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Q` | Quit application |
| `Ctrl+,` | Open settings |

---

## Troubleshooting

### Downloads failing

1. Check your internet connection
2. Update yt-dlp: `pip install --upgrade yt-dlp`
3. Increase retry attempts in Settings
4. Try increasing sleep between downloads

### FFmpeg not found

1. Click "Install FFmpeg" in Settings, or
2. Install manually and add to system PATH

### Spotify connection issues

1. Verify your Client ID is correct
2. Ensure redirect URI matches in Spotify dashboard
3. Check that no firewall is blocking port 8888

---

## Next Steps

- [Configuration Reference](configuration.md) - Advanced settings
- [Spotify Setup](spotify-setup.md) - Detailed Spotify API setup
- [CLI Guide](cli.md) - Command-line alternative
