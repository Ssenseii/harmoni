"""Spotify API worker thread for fetching playlists and tracks."""

from typing import Optional
from PySide6.QtCore import QThread, Signal

from spotify_api.client import NETWORK_ERROR_STATUS, SpotifyAPIError, SpotifyClient
from spotify_api.data_loader import SpotifyDataLoader

UNKNOWN_ERROR_STATUS = -1
LIKED_SONGS_ID = "__liked_songs__"


class SpotifyWorker(QThread):
    """
    Worker thread for Spotify API operations, running SpotifyDataLoader off the UI thread.

    Signals:
        playlists_loaded: Emitted when playlists are loaded
        tracks_loaded: Emitted when tracks are loaded
        liked_songs_loaded: Emitted when liked songs are loaded
        error: Emitted on error
        progress: Emitted during long operations
    """

    playlists_loaded = Signal(list)  # List of playlist dicts
    tracks_loaded = Signal(str, list)  # playlist_id, list of track dicts
    tracks_batch = Signal(str, list)  # playlist_id, batch of tracks (streaming)
    liked_songs_loaded = Signal(list)  # List of track dicts
    error = Signal(str)  # Error message
    error_status = Signal(int, str)  # HTTP status (0 network, -1 unknown), error message
    progress = Signal(str, int, int)  # message, current, total

    def __init__(self, config: dict, parent=None, *, client: Optional[SpotifyClient] = None):
        """Create the worker.

        @param config: HARMONI config.
        @param parent: Optional Qt parent.
        @param client: Shared SpotifyClient that holds the session token. A new one is built from config when omitted.
        """
        super().__init__(parent)
        self.config = config
        self._client = client
        self._task = None
        self._task_args = {}
        self._cancelled = False

    def fetch_playlists(self):
        """Queue task to fetch user playlists."""
        self._task = "playlists"
        self._task_args = {}
        self.start()

    def fetch_playlist_tracks(self, playlist_id: str, playlist_name: str = ""):
        """Queue task to fetch tracks from a playlist."""
        self._task = "playlist_tracks"
        self._task_args = {"playlist_id": playlist_id, "playlist_name": playlist_name}
        self.start()

    def fetch_liked_songs(self):
        """Queue task to fetch user's liked songs."""
        self._task = "liked_songs"
        self._task_args = {}
        self.start()

    def run(self):
        """Execute the queued task."""
        self._cancelled = False

        try:
            client = self._client or SpotifyClient(self.config)
            try:
                client.get_token()
            except SpotifyAPIError as e:
                network = e.status == NETWORK_ERROR_STATUS
                self._emit_error(NETWORK_ERROR_STATUS if network else 401, f"Failed to refresh token: {e}")
                return
            except RuntimeError:
                self._emit_error(401, "Not connected to Spotify. Please log in first.")
                return

            loader = SpotifyDataLoader(client)
            if self._task == "playlists":
                self._fetch_playlists(loader)
            elif self._task == "playlist_tracks":
                self._fetch_playlist_tracks(loader)
            elif self._task == "liked_songs":
                self._fetch_liked_songs(loader)

        except Exception as e:
            if not self._cancelled:
                status = e.status if isinstance(e, SpotifyAPIError) else UNKNOWN_ERROR_STATUS
                self._emit_error(status, str(e))

    def _emit_error(self, status: int, message: str):
        """Report a failure on both the plain and the status-carrying error signals.

        @param status: HTTP status, NETWORK_ERROR_STATUS, or UNKNOWN_ERROR_STATUS.
        @param message: Text for the user.
        """
        self.error_status.emit(status, message)
        self.error.emit(message)

    def _is_cancelled(self) -> bool:
        """Return whether cancel() was called, for the loader's should_cancel hook."""
        return self._cancelled

    def _batch_emitter(self, label: str, playlist_id: Optional[str] = None):
        """Build an on_batch callback that reports progress against the page total and streams tracks for playlist_id.

        @param label: Text shown in progress messages, for example "tracks from My Mix".
        @param playlist_id: Id sent with each tracks_batch emission. Nothing is streamed when omitted.
        """
        loaded = 0

        def on_batch(batch: list, total: int):
            nonlocal loaded
            if self._cancelled:
                return
            loaded += len(batch)
            if playlist_id is not None:
                self.tracks_batch.emit(playlist_id, batch)
            self.progress.emit(f"Loaded {loaded} of {total} {label}", loaded, total)

        return on_batch

    def _fetch_playlists(self, loader: SpotifyDataLoader):
        """Fetch all user playlists.

        @param loader: Loader bound to the session client.
        """
        self.progress.emit("Fetching playlists...", 0, 0)
        playlists = loader.list_all_playlists(
            limit=50, on_batch=self._batch_emitter("playlists"), should_cancel=self._is_cancelled
        )
        if not self._cancelled:
            self.playlists_loaded.emit(playlists)

    def _fetch_playlist_tracks(self, loader: SpotifyDataLoader):
        """Fetch tracks from a specific playlist.

        @param loader: Loader bound to the session client.
        """
        playlist_id = self._task_args.get("playlist_id")
        playlist_name = self._task_args.get("playlist_name", "")
        self.progress.emit(f"Fetching tracks from {playlist_name}...", 0, 0)
        tracks = loader.load_playlist_tracks(
            playlist_id,
            limit=100,
            on_batch=self._batch_emitter(f"tracks from {playlist_name}", playlist_id),
            should_cancel=self._is_cancelled,
        )
        if not self._cancelled:
            self.tracks_loaded.emit(playlist_id, tracks)

    def _fetch_liked_songs(self, loader: SpotifyDataLoader):
        """Fetch user's liked songs.

        @param loader: Loader bound to the session client.
        """
        self.progress.emit("Fetching liked songs...", 0, 0)
        tracks = loader.load_liked_songs(
            limit=50,
            on_batch=self._batch_emitter("liked songs", LIKED_SONGS_ID),
            should_cancel=self._is_cancelled,
        )
        if not self._cancelled:
            self.liked_songs_loaded.emit(tracks)

    def cancel(self):
        """Cancel the current operation."""
        self._cancelled = True
