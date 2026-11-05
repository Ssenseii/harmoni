import asyncio
import os
import time
import webbrowser
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import questionary

from utils.logger import log_info, log_warning, log_error
from utils.track_checker import (
    check_downloaded_files,
    existing_track_keys_in_dir,
    track_key,
)
from utils.loaders import load_primary_tracks, load_playlists, load_exportify_playlists
from downloader.base_downloader import download_track, batch_download
from downloader.playlist_download import download_playlist
from downloader.youtube_link_downloader import download_from_link, download_from_playlist
from menus.song_selection_menu import select_songs_for_playlist

NOT_FETCHABLE_REASON = "Spotify only lets apps read playlists you own or collaborate on"


def _sanitize_playlist_name(name: str) -> str:
    return (name or "").replace("/", "-").strip()


def _load_legacy_playlists(config: dict) -> list:
    """Return the named playlists from playlists_file as [{'name', 'tracks'}, ...].

    @param config: App config holding playlists_file.
    """
    playlists = []
    for pl in load_playlists(config["playlists_file"]) or []:
        name = (pl.get("name") or "").strip()
        if name:
            playlists.append({"name": name, "tracks": pl.get("tracks") or []})
    return playlists


def _spotify_setup_help(config: dict) -> None:
    try:
        from config import DEFAULT_CONFIG
        from spotify_api.auth import check_spotify_credentials, spotify_app_setup_instructions

        creds = check_spotify_credentials(config)
        log_info("\n" + "=" * 72)
        log_info("SPOTIFY WEB API SETUP")
        log_info("=" * 72)
        log_info(spotify_app_setup_instructions(redirect_uri=creds.get("redirect_uri") or DEFAULT_CONFIG["spotify_redirect_uri"]))
        log_info("")
        log_info("Current config status:")
        log_info(f"- spotify_client_id: {('SET' if (config.get('spotify_client_id') or '').strip() else 'NOT SET (required)')}")
        log_info(f"- spotify_redirect_uri: {creds.get('redirect_uri') or ''}")
        log_info(f"- spotify_scopes: {', '.join(creds.get('scopes') or [])}")
        log_info("")
        if not creds.get("ok"):
            log_warning(creds.get("message") or "Spotify credentials are incomplete.")
        else:
            log_info(creds.get("message") or "Spotify credentials look OK.")
        log_info("=" * 72 + "\n")
    except Exception as e:
        log_error(f"Failed to show Spotify setup help: {e}")


def _spotify_token_status(config: dict) -> str:
    try:
        from spotify_api.token_manager import TokenManager

        tm = TokenManager()
        token = tm.load(config)
        if token is None:
            return "No cached Spotify token found."
        expired = tm.is_expired(token)
        exp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(token.expires_at)))
        return f"Token cached: YES | Expired: {'YES' if expired else 'NO'} | Expires at: {exp_str}"
    except Exception as e:
        return f"Token status unavailable: {e}"


def _spotify_authenticate(config: dict) -> None:
    """Run an interactive PKCE flow where the user pastes the redirect URL back into the CLI."""
    try:
        from spotify_api.auth import (
            SpotifyPKCEAuth,
            check_spotify_credentials,
            extract_code_from_redirect_url,
        )

        creds = check_spotify_credentials(config)
        if not creds.get("ok"):
            _spotify_setup_help(config)
            return

        auth = SpotifyPKCEAuth(config)
        flow = auth.begin_oauth_flow(show_dialog=True)
        auth_url = flow["auth_url"]
        pkce_pair = flow["pkce_pair"]
        state = flow["state"]

        redirect_uri = str(config.get("spotify_redirect_uri") or "").strip()

        log_info("\n" + "=" * 72)
        log_info("SPOTIFY AUTHENTICATION")
        log_info("=" * 72)
        log_info("1) A browser login will open (or you can copy/paste the URL).")
        log_info("2) After approving, Spotify will redirect you to your redirect_uri.")
        log_info("3) HARMONI will auto-capture the redirect (no copy/paste needed) if it can bind the loopback callback.")
        log_info("   If it cannot (port in use / firewall / non-loopback redirect), you can still paste the URL manually.")
        log_info("")
        log_info(f"Authorize URL:\n{auth_url}")
        log_info("=" * 72)

        # --- Minimal local callback server (loopback only) ---
        server = None
        server_thread = None
        callback_result = {"full_url": None, "error": None}

        parsed_redirect = urllib.parse.urlparse(redirect_uri) if redirect_uri else None
        can_listen = bool(
            parsed_redirect
            and parsed_redirect.scheme == "http"
            and (parsed_redirect.hostname in ("127.0.0.1", "::1"))
            and (parsed_redirect.port is not None)
            and (parsed_redirect.path or "/")
        )

        if can_listen:
            host = parsed_redirect.hostname
            port = int(parsed_redirect.port)
            expected_path = parsed_redirect.path or "/"

            # In Docker, binding to 127.0.0.1 only listens on the container loopback and
            # won't accept traffic coming from the host via published ports.
            running_in_docker = os.path.exists("/.dockerenv") or bool(os.environ.get("container"))
            bind_host = host
            if running_in_docker and host == "127.0.0.1":
                bind_host = "0.0.0.0"

            class _SpotifyCallbackHandler(BaseHTTPRequestHandler):
                def do_GET(self):  # noqa: N802 (stdlib naming)
                    try:
                        path, _, query = self.path.partition("?")
                        if path != expected_path:
                            self.send_response(404)
                            self.send_header("Content-Type", "text/plain; charset=utf-8")
                            self.end_headers()
                            self.wfile.write(b"Not Found")
                            return

                        # Reconstruct the full redirect URL so we can reuse existing parsing.
                        if query:
                            full = f"{redirect_uri}?{query}"
                        else:
                            full = redirect_uri

                        callback_result["full_url"] = full

                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(
                            (
                                "<html><head><title>HARMONI</title></head><body>"
                                "<h2>Spotify authentication received.</h2>"
                                "<p>You can close this tab and return to the terminal.</p>"
                                "</body></html>"
                            ).encode("utf-8")
                        )
                    finally:
                        # Shut down the server after the first request (in a separate thread).
                        try:
                            threading.Thread(target=self.server.shutdown, daemon=True).start()
                        except Exception:
                            pass

                def log_message(self, format, *args):  # noqa: A003
                    # Silence default HTTP request logging.
                    return

            try:
                server = HTTPServer((bind_host, port), _SpotifyCallbackHandler)

                def _serve_once() -> None:
                    try:
                        server.serve_forever(poll_interval=0.1)
                    except Exception as e:
                        callback_result["error"] = str(e)

                server_thread = threading.Thread(target=_serve_once, daemon=True)
                server_thread.start()
                log_info(f"Local callback server started: {redirect_uri}")
                if bind_host != host:
                    log_info(f"(Docker detected) Bound callback server to {bind_host}:{port} so host port-forwarding can reach it.")
            except Exception as e:
                log_warning(f"Could not start local callback server on {redirect_uri}: {e}")
                server = None

        if questionary.confirm("Open the authorize URL in your default browser?", default=True).ask():
            try:
                webbrowser.open(auth_url)
            except Exception:
                pass

        # If the callback server is running, wait for it to receive the redirect.
        pasted = ""
        if server is not None:
            log_info("Waiting for Spotify redirect to hit the local callback (timeout: 180 seconds)...")
            start = time.time()
            while time.time() - start < 180:
                if callback_result.get("full_url"):
                    pasted = str(callback_result["full_url"]).strip()
                    break
                if callback_result.get("error"):
                    break
                time.sleep(0.1)

            if not pasted:
                log_warning("Did not receive a callback within the timeout (or the callback server failed).")

        # Fallback: ask user to paste the redirect URL or raw code.
        if not pasted:
            pasted = questionary.text(
                "Paste the full redirect URL (preferred) OR just the code=... value:"
            ).ask()

        pasted = (pasted or "").strip()
        if not pasted:
            log_warning("No redirect URL / code provided. Cancelling auth.")
            return

        code = ""
        parsed_state = ""
        if "http://" in pasted or "https://" in pasted:
            parsed = extract_code_from_redirect_url(pasted)
            if parsed.get("error"):
                log_error(f"Spotify returned an error: {parsed.get('error')}")
                return
            code = parsed.get("code", "")
            parsed_state = parsed.get("state", "")
        else:
            # Assume user pasted the raw code.
            code = pasted

        if not code:
            log_error("Could not find an authorization code. Paste the full redirect URL that contains ?code=...")
            return

        if parsed_state and parsed_state != state:
            log_error("OAuth state mismatch. For safety, cancelling this authentication attempt.")
            log_info("Tip: Make sure you paste the redirect URL from the most recent login attempt.")
            return

        token = auth.exchange_code_for_token(code=code, code_verifier=pkce_pair.code_verifier)
        exp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(token.expires_at)))
        log_info(f"✅ Spotify authentication successful. Token expires at: {exp_str}")
    except Exception as e:
        log_error(f"Spotify authentication failed: {e}")


def _spotify_download_from_playlists(config: dict) -> None:
    try:
        from spotify_api.client import SpotifyClient
        from spotify_api.data_loader import SpotifyDataLoader

        client = SpotifyClient(config)

        # Trigger token load/refresh early so we can provide a good message.
        try:
            _ = client.get_token()
        except Exception as e:
            log_warning(f"Spotify token not available: {e}")
            log_info("Run 'Authenticate with Spotify' first.")
            return

        loader = SpotifyDataLoader(client)

        try:
            me = loader.current_user()
            display = (me.get("display_name") or me.get("id") or "").strip()
            if display:
                log_info(f"Signed in as: {display}")
        except Exception:
            # Non-fatal; continue.
            pass

        playlists = loader.list_all_playlists(limit=50)
        if not playlists:
            log_info("No playlists found for this account.")
            return

        choices = []
        by_id = {}
        for p in playlists:
            pid = (p.get("id") or "").strip()
            if not pid:
                continue
            by_id[pid] = p
            name = (p.get("name") or "(unnamed)").strip()
            owner = (p.get("owner") or "").strip()
            total = p.get("tracks_total")
            total_str = f"{int(total)}" if isinstance(total, int) else (str(total) if total is not None else "?")
            title = f"{name} ({total_str} tracks)" + (f" — {owner}" if owner else "")
            disabled = None if p.get("fetchable", True) else NOT_FETCHABLE_REASON
            choices.append(questionary.Choice(title=title, value=pid, disabled=disabled))

        if not choices:
            log_info("No usable playlists returned by Spotify.")
            return

        selected_ids = questionary.checkbox(
            "Select Spotify playlists to download (space toggles, enter confirms):",
            choices=choices,
        ).ask()

        if not selected_ids:
            log_warning("❌ No playlists selected.")
            log_info("")
            log_info("💡 How to use the checkbox interface:")
            log_info("   • Use ↑↓ arrows to navigate")
            log_info("   • Press SPACE to select/deselect")
            log_info("   • Press ENTER to confirm")
            log_info("")
            return

        # Limit for safety; users can re-run if they want more.
        max_tracks = questionary.text(
            "Max tracks to load per playlist (blank = no limit; recommended: 300):",
            default="300",
        ).ask()
        max_tracks = (max_tracks or "").strip()
        max_tracks_int = int(max_tracks) if max_tracks.isdigit() else None

        for pid in selected_ids:
            p = by_id.get(pid) or {}
            pl_name = (p.get("name") or "Spotify Playlist").strip()
            if not p.get("fetchable", True):
                log_warning(f"Skipped '{pl_name}': {NOT_FETCHABLE_REASON}. Export it with Exportify and use the CSV import.")
                continue

            log_info("")
            log_info(f"Loading playlist from Spotify: {pl_name}")
            tracks = loader.load_playlist_tracks(
                pid,
                max_tracks=max_tracks_int,
            )
            if not tracks:
                log_warning(f"Playlist '{pl_name}' returned 0 tracks (or tracks were not usable).")
                continue

            playlist_dir = os.path.join(config["output_dir"], _sanitize_playlist_name(pl_name))
            existing = existing_track_keys_in_dir(playlist_dir)
            exists_count = sum(1 for t in tracks if track_key(t) in existing)

            log_info(f"Playlist: {pl_name}")
            log_info(f"  Total tracks loaded: {len(tracks)}")
            log_info(f"  Already exists in folder: {exists_count}")

            selected_tracks = select_songs_for_playlist(
                playlist_name=pl_name,
                tracks=tracks,
                playlist_dir=playlist_dir,
            )

            if not selected_tracks:
                log_info(f"❌ Skipped playlist: {pl_name}")
                continue

            confirm = questionary.confirm(
                f"Download {len(selected_tracks)} selected tracks into '{pl_name}'?",
                default=True,
            ).ask()
            if not confirm:
                log_info(f"❌ Skipped playlist: {pl_name}")
                continue

            asyncio.run(
                download_playlist(
                    pl_name,
                    selected_tracks,
                    config["output_dir"],
                    config["audio_format"],
                    config["sleep_between"],
                    config=config,
                )
            )

    except Exception as e:
        log_error(f"Spotify playlist download failed: {e}")


def _spotify_download_liked_songs(config: dict) -> None:
    try:
        from spotify_api.client import SpotifyClient
        from spotify_api.data_loader import SpotifyDataLoader

        client = SpotifyClient(config)
        try:
            _ = client.get_token()
        except Exception as e:
            log_warning(f"Spotify token not available: {e}")
            log_info("Run 'Authenticate with Spotify' first.")
            return

        loader = SpotifyDataLoader(client)

        max_tracks = questionary.text(
            "Max liked songs to load (blank = no limit; recommended: 500):",
            default="500",
        ).ask()
        max_tracks = (max_tracks or "").strip()
        max_tracks_int = int(max_tracks) if max_tracks.isdigit() else None

        log_info("Loading liked songs from Spotify...")
        tracks = loader.load_liked_songs(max_tracks=max_tracks_int)
        if not tracks:
            log_info("No liked songs returned (or none were usable).")
            return

        playlist_name = "Liked Songs"
        playlist_dir = os.path.join(config["output_dir"], _sanitize_playlist_name(playlist_name))
        existing = existing_track_keys_in_dir(playlist_dir)
        exists_count = sum(1 for t in tracks if track_key(t) in existing)

        log_info(f"Liked Songs")
        log_info(f"  Total tracks loaded: {len(tracks)}")
        log_info(f"  Already exists in folder: {exists_count}")

        selected_tracks = select_songs_for_playlist(
            playlist_name=playlist_name,
            tracks=tracks,
            playlist_dir=playlist_dir,
        )

        if not selected_tracks:
            log_info("❌ Skipped liked songs.")
            return

        confirm = questionary.confirm(
            f"Download {len(selected_tracks)} selected tracks into '{playlist_name}'?",
            default=True,
        ).ask()
        if not confirm:
            log_info("❌ Skipped liked songs.")
            return

        asyncio.run(
            download_playlist(
                playlist_name,
                selected_tracks,
                config["output_dir"],
                config["audio_format"],
                config["sleep_between"],
                config=config,
            )
        )

    except Exception as e:
        log_error(f"Spotify liked songs download failed: {e}")


def _spotify_api_menu(config: dict) -> None:
    while True:
        log_info("")
        log_info("Spotify status: " + _spotify_token_status(config))

        choice = questionary.select(
            "🎧 Spotify Web API — What would you like to do?",
            choices=[
                "Authenticate with Spotify (OAuth PKCE)",
                "Download from my playlists",
                "Download from liked songs",
                "Spotify API credential setup help",
                "Log out (clear cached token)",
                "Back",
            ],
        ).ask()

        if choice == "Authenticate with Spotify (OAuth PKCE)":
            _spotify_authenticate(config)

        elif choice == "Download from my playlists":
            _spotify_download_from_playlists(config)

        elif choice == "Download from liked songs":
            _spotify_download_liked_songs(config)

        elif choice == "Spotify API credential setup help":
            _spotify_setup_help(config)

        elif choice == "Log out (clear cached token)":
            try:
                from spotify_api.token_manager import TokenManager

                ok = TokenManager().clear()
                if ok:
                    log_info("✅ Cleared cached Spotify token.")
                else:
                    log_warning("Could not clear token cache (it may not exist).")
            except Exception as e:
                log_error(f"Failed to clear Spotify token cache: {e}")

        elif choice == "Back":
            break


def downloads_menu(config):
    """Displays the Downloads menu and handles related actions."""

    while True:
        choice = questionary.select(
            "📥 Downloads Menu — What would you like to do?",
            choices=[
                "Download all pending (sequential) - Works with CSV and JSON sources",
                "Download all pending (batch async) - Works with CSV and JSON sources",
                "Search & Download a single track",
                "Spotify Web API (OAuth) — Playlists / Liked Songs",
                "Download from Exportify CSV folder",
                "Download from playlists file (legacy Spotify export)",
                "Download from YouTube link/playlist",
                "Back",
            ],
        ).ask()

        if choice == "Download all pending (sequential) - Works with CSV and JSON sources":
            tracks = load_primary_tracks(config)

            if not tracks:
                log_warning("No tracks found. Please check your configuration and source files.")
                continue

            _, pending = check_downloaded_files(config["output_dir"], tracks)
            log_info(f"Total tracks: {len(tracks)} | Pending: {len(pending)}")

            if not pending:
                log_info("✅ All tracks already downloaded. Nothing to do.")
                continue

            log_info(f"Downloading {len(pending)} tracks sequentially...")
            for t in pending:
                download_track(
                    t["artist"],
                    t["track"],
                    config["output_dir"],
                    config["audio_format"],
                    config["sleep_between"],
                    config=config,
                )

        elif choice == "Download all pending (batch async) - Works with CSV and JSON sources":
            tracks = load_primary_tracks(config)

            if not tracks:
                log_warning("No tracks found. Please check your configuration and source files.")
                continue

            _, pending = check_downloaded_files(config["output_dir"], tracks)
            log_info(f"Total tracks: {len(tracks)} | Pending: {len(pending)}")

            if not pending:
                log_info("✅ All tracks already downloaded. Nothing to do.")
                continue

            log_info(f"Downloading {len(pending)} tracks in batch async mode...")
            asyncio.run(batch_download(
                pending, config["output_dir"], config["audio_format"], config=config, save_progress_first=True
            ))

        elif choice == "Search & Download a single track":
            artist = questionary.text("Enter artist name (leave empty if unknown):").ask()
            artist = (artist.strip() if artist else "").strip()

            song = questionary.text("Enter song title (required):").ask()
            song = (song.strip() if song else "").strip()

            if not song:
                log_warning("Song title is required. Please try again.")
                continue

            if not artist:
                artist = "Unknown Artist"
                log_info(f"No artist provided. Using fallback artist: {artist}")

            download_track(
                artist,
                song,
                config["output_dir"],
                config["audio_format"],
                config["sleep_between"],
                config=config,
            )

        elif choice == "Spotify Web API (OAuth) — Playlists / Liked Songs":
            _spotify_api_menu(config)

        elif choice == "Download from playlists file (legacy Spotify export)":
            playlists = _load_legacy_playlists(config)

            if not playlists:
                log_info("No playlists found in playlists file.")
                continue

            pending = []
            for pl in playlists:
                playlist_dir = os.path.join(config["output_dir"], _sanitize_playlist_name(pl["name"]))
                existing = existing_track_keys_in_dir(playlist_dir)
                missing_count = 0
                for t in pl["tracks"]:
                    if track_key(t) not in existing:
                        missing_count += 1
                if missing_count > 0:
                    pending.append(pl)

            if not pending:
                log_info("No playlists pending download.")
                continue

            sub_choice = questionary.select(
                "Select download mode:",
                choices=["Download ALL pending playlists", "Pick which playlists to download"],
            ).ask()

            to_download = pending if sub_choice == "Download ALL pending playlists" else []

            if sub_choice == "Pick which playlists to download":
                choices = [
                    questionary.Choice(title=f"{pl['name']} ({len(pl['tracks'])} tracks)", value=pl["name"])
                    for pl in pending
                ]
                selected_names = questionary.checkbox(
                    "Select playlists to download (space to toggle, enter to confirm):",
                    choices=choices,
                ).ask()

                if not selected_names:
                    log_warning("❌ No playlists selected.")
                    log_info("")
                    log_info("💡 How to use the checkbox interface:")
                    log_info("   • Use ↑↓ arrows to navigate")
                    log_info("   • Press SPACE to select/deselect")
                    log_info("   • Press ENTER to confirm")
                    log_info("")
                    continue

                to_download = [pl for pl in pending if pl["name"] in selected_names]

            for playlist in to_download:
                playlist_dir = os.path.join(config["output_dir"], _sanitize_playlist_name(playlist["name"]))
                existing = existing_track_keys_in_dir(playlist_dir)
                exists_count = sum(1 for t in playlist["tracks"] if track_key(t) in existing)

                log_info(f"Playlist: {playlist['name']}")
                log_info(f"  Total tracks: {len(playlist['tracks'])}")
                log_info(f"  Already exists in folder: {exists_count}")

                selected_tracks = select_songs_for_playlist(
                    playlist_name=playlist["name"],
                    tracks=playlist["tracks"],
                    playlist_dir=playlist_dir,
                )

                if not selected_tracks:
                    log_info(f"❌ Skipped playlist: {playlist['name']}")
                    continue

                confirm = questionary.confirm(
                    f"Download {len(selected_tracks)} selected tracks into '{playlist['name']}'?",
                    default=True,
                ).ask()
                if not confirm:
                    log_info(f"❌ Skipped playlist: {playlist['name']}")
                    continue

                asyncio.run(
                    download_playlist(
                        playlist["name"],
                        selected_tracks,
                        config["output_dir"],
                        config["audio_format"],
                        config["sleep_between"],
                    )
                )

        elif choice == "Download from Exportify CSV folder":
            exportify_dir = config.get("exportify_watch_folder", "data/exportify")
            playlists = load_exportify_playlists(exportify_dir)

            if not playlists:
                log_info("No CSV playlists found in exportify folder.")
                continue

            choices = [
                questionary.Choice(title=f"{pl['name']} ({len(pl['tracks'])} tracks)", value=pl["name"])
                for pl in playlists
            ]
            selected_names = questionary.checkbox(
                "Select playlists to download (space to toggle, enter to confirm):",
                choices=choices,
            ).ask()

            if not selected_names:
                log_warning("❌ No playlists selected.")
                log_info("")
                log_info("💡 How to use the checkbox interface:")
                log_info("   • Use ↑↓ arrows to navigate between playlists")
                log_info("   • Press SPACE to select/deselect a playlist")
                log_info("   • Selected items will be marked with ✓")
                log_info("   • Press ENTER when finished to confirm your selection")
                log_info("")

                retry = questionary.select(
                    "What would you like to do?",
                    choices=["Try selecting playlists again", "Back to Downloads menu"],
                ).ask()

                if retry == "Try selecting playlists again":
                    selected_names = questionary.checkbox(
                        "Select playlists to download (space to toggle, enter to confirm):",
                        choices=choices,
                    ).ask()

                    if not selected_names:
                        log_info("No playlists selected. Returning to Downloads menu.")
                        continue
                else:
                    continue

            for name in selected_names:
                playlist = next(pl for pl in playlists if pl["name"] == name)

                playlist_dir = os.path.join(config["output_dir"], _sanitize_playlist_name(playlist["name"]))
                existing = existing_track_keys_in_dir(playlist_dir)
                exists_count = sum(1 for t in playlist["tracks"] if track_key(t) in existing)

                log_info(f"Playlist: {playlist['name']}")
                log_info(f"  Total tracks: {len(playlist['tracks'])}")
                log_info(f"  Already exists in folder: {exists_count}")

                selected_tracks = select_songs_for_playlist(
                    playlist_name=playlist["name"],
                    tracks=playlist["tracks"],
                    playlist_dir=playlist_dir,
                )

                if not selected_tracks:
                    log_info(f"❌ Skipped playlist: {playlist['name']}")
                    continue

                confirm = questionary.confirm(
                    f"Download {len(selected_tracks)} selected tracks into '{playlist['name']}'?",
                    default=True,
                ).ask()

                if not confirm:
                    log_info(f"❌ Skipped playlist: {playlist['name']}")
                    continue

                asyncio.run(
                    download_playlist(
                        playlist["name"],
                        selected_tracks,
                        config["output_dir"],
                        config["audio_format"],
                        config["sleep_between"],
                    )
                )

        elif choice == "Download from YouTube link/playlist":
            url = questionary.text("Paste YouTube video or playlist URL:").ask()
            if not url:
                log_warning("No URL provided.")
                continue

            if "playlist" in url.lower():
                download_from_playlist(url, config["output_dir"], config["audio_format"], config["sleep_between"], config=config)
            else:
                download_from_link(url, config["output_dir"], config["audio_format"], config=config)

        elif choice == "Back":
            log_info("Returning to main menu...")
            break

