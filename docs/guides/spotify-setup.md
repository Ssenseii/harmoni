# Spotify Web API Setup

HARMONI can load tracks directly from your Spotify account (playlists + liked songs) via OAuth PKCE authentication.

## What You Need

- A Spotify account
- Your own Spotify Developer app with a **Client ID**
- Spotify Premium on the account that owns the Developer app
- Redirect URI: `http://127.0.0.1:8888/callback`

> **Note:** This project uses Authorization Code + PKCE, so **no client secret is required**.

---

## Step 1: Create a Spotify Developer App

1. Go to https://developer.spotify.com/dashboard
2. Create a new app (or select an existing one)
3. In app settings, add this Redirect URI **exactly**:
   ```
   http://127.0.0.1:8888/callback
   ```
4. Copy your **Client ID**

## Step 1b: Allow Your Users

New Spotify apps run in **Development Mode**. In that mode:

- The app owner must have **Spotify Premium**.
- Only listed users can log in. Open the app in the dashboard, go to **User Management**, and add every person who will use HARMONI by their Spotify account email. Add yourself too.
- The app can only read playlists that belong to the logged-in user. Other people's public playlists return HTTP 403.

---

## Step 2: Configure HARMONI

Add your Client ID to `config.json`:

```json
{
  "spotify_client_id": "your-client-id-here",
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

### Configuration Options

| Setting | Description |
|---------|-------------|
| `spotify_client_id` | Your Spotify Developer app Client ID |
| `spotify_redirect_uri` | Must match your app's Redirect URI exactly |
| `spotify_scopes` | Permissions to request (defaults support playlists + liked songs) |
| `spotify_cache_tokens` | Cache tokens to avoid re-authenticating |
| `spotify_auto_refresh` | Automatically refresh expired tokens |

> **Note:** Spotify no longer allows `localhost` as a redirect URI. Use `127.0.0.1` instead.

---

## Step 3: Authenticate in the App

1. Run the application
2. Go to: **Downloads Menu > Spotify Web API (OAuth) — Playlists / Liked Songs**
3. Select: **Authenticate with Spotify (OAuth PKCE)**
4. The app will show an authorization URL and offer to open it in your browser
5. Approve the permissions in Spotify
6. HARMONI captures the redirect automatically via a local callback server
   - If the port is in use, you'll be asked to paste the redirect URL manually

Tokens are cached at `data/spotify_tokens.json` when enabled.

In the desktop app, **Connect to Spotify** checks for a Client ID first. Without one it shows these setup steps and an **Open Settings** button instead of opening the browser.

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| Spotify shows `redirect_uri: Not matching configuration` | The Redirect URI in your Spotify app must be exactly `http://127.0.0.1:8888/callback`, and `spotify_client_id` must be your own app's Client ID |
| HTTP 403 after logging in | Add your Spotify email under User Management, make sure the app owner has Premium, and only load your own playlists |
| HTTP 429 | Spotify is rate limiting. Wait a minute and try again |
| `Port 8888 is already in use` | Another program holds the port. Approve in the browser, then paste the full address from the address bar into the manual entry box |

---

## Step 4: Download Your Music

From the Spotify menu, you can:

- **Download from my playlists** - Select which playlists to download
- **Download from liked songs** - Download your saved tracks

You'll be prompted to:
- Pick playlists (checkbox UI)
- Optionally limit the number of tracks loaded
- Select individual tracks from each playlist

---

## Legacy Alternative: File-Based Imports

If you prefer not to use the Spotify API, HARMONI supports file-based workflows:

### Option A: Exportify (Recommended)

1. Go to https://exportify.net/
2. Log in with Spotify
3. Export your playlists as CSV files
4. Place CSVs in `data/exportify/`
5. Use **Download from Exportify CSVs** in the app

### Option B: Official Spotify Data Export

1. Request your data at Spotify's Privacy page
2. Wait for the email with your ZIP file
3. Extract `YourLibrary.json`
4. Convert or use as the basis for `data/tracks.json`
