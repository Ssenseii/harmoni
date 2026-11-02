import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .auth import SpotifyPKCEAuth
from .token_manager import TokenInfo, TokenManager
from utils.logger import log_warning


SPOTIFY_API_BASE_URL = "https://api.spotify.com/v1"
NETWORK_ERROR_STATUS = 0
DEFAULT_MAX_RETRY_AFTER = 30.0


class SpotifyAPIError(RuntimeError):
    """A failed Spotify request with its HTTP status (0 for network failures) and endpoint."""

    def __init__(self, status: int, endpoint: str, message: str):
        """Build the error and its display text.

        @param status: HTTP status code, or NETWORK_ERROR_STATUS when no response arrived.
        @param endpoint: Method and path that failed, for example "GET /me/playlists".
        @param message: Server or transport detail for the user.
        """
        self.status = int(status)
        self.endpoint = endpoint
        self.message = message
        text = f"Spotify API error {self.status}: {message}" if self.status else message
        super().__init__(text)


class SessionTokenManager(TokenManager):
    """TokenManager that also keeps the latest token in memory, so a session works with spotify_cache_tokens off."""

    def __init__(self, **kwargs: Any):
        """Create the manager with an empty in-memory slot.

        @param kwargs: Passed to TokenManager, for example cache_path.
        """
        super().__init__(**kwargs)
        self._memory: Optional[TokenInfo] = None

    def load(self, config: Dict[str, Any]) -> Optional[TokenInfo]:
        """Return the in-memory token, or the disk cache when none is held.

        @param config: HARMONI config, which decides whether the disk cache is used.
        """
        return self._memory or super().load(config)

    def save(self, config: Dict[str, Any], token: TokenInfo) -> bool:
        """Hold the token in memory and persist it when caching is enabled.

        @param config: HARMONI config, which decides whether the disk cache is used.
        @param token: Token to keep.
        """
        self._memory = token
        return super().save(config, token)

    def clear(self) -> bool:
        """Forget the in-memory token and remove the disk cache."""
        self._memory = None
        return super().clear()


class SpotifyClient:
    """Thin Spotify Web API client (stdlib-only).

    This client expects an OAuth access token (Authorization Code w/ PKCE).

    Design goals:
    - Centralize retry + rate limiting (429 Retry-After)
    - Provide high-level helpers that return *fully paged* lists
    """

    def __init__(self, config: Dict[str, Any], *, token_manager: Optional[TokenManager] = None):
        self.config = config or {}
        self.token_manager = token_manager or TokenManager()
        self._token: Optional[TokenInfo] = None
        self._refresh_lock = threading.Lock()

    # -----------------
    # Token management
    # -----------------

    def set_token(self, token: TokenInfo) -> None:
        self._token = token
        self.token_manager.save(self.config, token)

    def get_token(self) -> TokenInfo:
        if self._token is None:
            self._token = self.token_manager.load(self.config)

        if self._token is None:
            raise RuntimeError("No Spotify token available. Run the OAuth PKCE flow first.")

        if not self.token_manager.is_expired(self._token):
            return self._token

        if not bool(self.config.get("spotify_auto_refresh", True)):
            raise RuntimeError("Spotify token expired and spotify_auto_refresh is disabled.")

        if not self._token.refresh_token:
            raise RuntimeError("Spotify token expired and no refresh_token is available.")

        return self._refresh_token(self._token, only_if_expired=True)

    def _refresh_token(self, stale: TokenInfo, *, only_if_expired: bool) -> TokenInfo:
        """Refresh the token once across threads, returning a newer token another thread already got.

        @param stale: The token the caller found unusable.
        @param only_if_expired: Skip the refresh when the current token is not expired.
        """
        with self._refresh_lock:
            current = self._token
            if current is not None and current is not stale:
                return current
            if only_if_expired and current is not None and not self.token_manager.is_expired(current):
                return current
            auth = SpotifyPKCEAuth(self.config, token_manager=self.token_manager)
            refreshed = auth.refresh_access_token(refresh_token=stale.refresh_token)
            self._token = refreshed
            return refreshed

    # -----------------
    # HTTP helpers
    # -----------------

    def _sleep_with_jitter(self, seconds: float) -> None:
        # Avoid synchronized retries when running concurrent calls.
        seconds = float(max(0.0, seconds))
        jitter = float(self.config.get("spotify_retry_jitter", 0.25))
        time.sleep(seconds + (jitter * (time.time() % 1.0)))

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        retry_429: bool = True,
        retry_5xx: bool = True,
        retry_401_refresh: bool = True,
    ) -> Dict[str, Any]:
        """Make a Spotify Web API request and return parsed JSON.

        Retry behavior:
        - 429: honors Retry-After (Spotify rate limiting)
        - 5xx: exponential backoff retries (best effort)
        - 401: one refresh attempt if possible
        """

        max_retries = int(self.config.get("spotify_max_retries", 5))
        backoff_base = float(self.config.get("spotify_backoff_base", 1.0))

        attempt = 0
        while True:
            attempt += 1
            token = self.get_token()

            url = f"{SPOTIFY_API_BASE_URL}{path}"
            if params:
                url = f"{url}?{urllib.parse.urlencode({k: str(v) for k, v in params.items() if v is not None})}"

            req = urllib.request.Request(
                url=url,
                method=method.upper(),
                headers={
                    "Authorization": f"{token.token_type} {token.access_token}",
                    "Accept": "application/json",
                },
            )

            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8")
                    status = getattr(resp, "status", 200)
                    headers = dict(resp.headers)
            except urllib.error.HTTPError as e:
                status = e.code
                headers = dict(getattr(e, "headers", {}) or {})
                body = (e.read().decode("utf-8") if hasattr(e, "read") else "")

                # --- Diagnostics for common auth issues (401/403) ---
                if status in (401, 403):
                    www_auth = headers.get("WWW-Authenticate") or headers.get("www-authenticate")
                    msg = None
                    try:
                        payload = json.loads(body) if body else {}
                        if isinstance(payload, dict):
                            err = payload.get("error")
                            if isinstance(err, dict):
                                msg = err.get("message")
                    except Exception:
                        msg = None

                    desired_scopes = [str(s).strip() for s in (self.config.get("spotify_scopes") or []) if str(s).strip()]
                    token_scopes = [s for s in str(getattr(self._token, "scope", "") or "").split() if s]
                    missing_scopes = sorted(set(desired_scopes) - set(token_scopes))

                    # Keep logs actionable and avoid leaking secrets.
                    log_warning(
                        "Spotify API auth failure diagnostics:\n"
                        f"- HTTP status: {status}\n"
                        f"- Endpoint: {method.upper()} {path}\n"
                        + (f"- WWW-Authenticate: {www_auth}\n" if www_auth else "")
                        + (f"- Error message: {msg}\n" if msg else "")
                        + (f"- Token scope: {getattr(self._token, 'scope', None)}\n" if self._token else "- Token scope: <no token loaded>\n")
                        + (f"- Config spotify_scopes: {desired_scopes}\n" if desired_scopes else "- Config spotify_scopes: []\n")
                        + (f"- Missing scopes vs config: {missing_scopes}\n" if missing_scopes else "")
                        + (f"- Raw body: {body}" if body else "")
                    )

                # 401: token invalid/expired (server-side); try refresh once.
                if status == 401 and retry_401_refresh and attempt <= max_retries:
                    if token.refresh_token and bool(self.config.get("spotify_auto_refresh", True)):
                        try:
                            self._refresh_token(token, only_if_expired=False)
                            retry_401_refresh = False
                            continue
                        except Exception:
                            # fall through to raise
                            pass

                # 429: rate limited.
                if status == 429 and retry_429 and attempt <= max_retries:
                    retry_after = headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after is not None else 1.0
                    except Exception:
                        delay = 1.0
                    max_retry_after = float(self.config.get("spotify_max_retry_after", DEFAULT_MAX_RETRY_AFTER))
                    self._sleep_with_jitter(min(max_retry_after, max(1.0, delay)))
                    continue

                # 5xx: transient errors.
                if status >= 500 and retry_5xx and attempt <= max_retries:
                    delay = backoff_base * (2 ** max(0, attempt - 1))
                    self._sleep_with_jitter(min(60.0, delay))
                    continue

                # Prefer the server-provided message when available.
                detail = body
                try:
                    payload = json.loads(body) if body else {}
                    if isinstance(payload, dict) and isinstance(payload.get("error"), dict) and payload["error"].get("message"):
                        detail = str(payload["error"].get("message"))
                except Exception:
                    pass

                raise SpotifyAPIError(status, f"{method.upper()} {path}", detail) from e
            except Exception as e:
                if attempt <= max_retries:
                    delay = backoff_base * (2 ** max(0, attempt - 1))
                    self._sleep_with_jitter(min(30.0, delay))
                    continue
                raise SpotifyAPIError(
                    NETWORK_ERROR_STATUS, f"{method.upper()} {path}", f"Spotify API request failed: {e}"
                ) from e

            if not body:
                return {}

            try:
                return json.loads(body)
            except Exception as e:
                raise RuntimeError(f"Spotify API response was not JSON (status {status}): {body}") from e

    def _paginate(self, path: str, *, params: Optional[Dict[str, Any]] = None, page_key: str = "items") -> List[Dict[str, Any]]:
        """Fetch all pages for an endpoint that returns {items, total, limit, offset}."""

        out: List[Dict[str, Any]] = []
        limit = int((params or {}).get("limit") or 50)
        offset = int((params or {}).get("offset") or 0)

        while True:
            page = self.request_json("GET", path, params={**(params or {}), "limit": limit, "offset": offset})
            items = page.get(page_key) or []
            if isinstance(items, list):
                out.extend([x for x in items if isinstance(x, dict)])

            total = page.get("total")
            if total is None:
                break

            got = len(items) if isinstance(items, list) else 0
            offset += got
            if got <= 0 or offset >= int(total):
                break

        return out

    # -----------------
    # Convenience endpoints
    # -----------------

    def me(self) -> Dict[str, Any]:
        return self.request_json("GET", "/me")

    def current_user_playlists(self, *, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        return self.request_json("GET", "/me/playlists", params={"limit": limit, "offset": offset})

    def playlist_items(self, playlist_id: str, *, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        return self.request_json(
            "GET",
            f"/playlists/{playlist_id}/items",
            params={"limit": limit, "offset": offset, "additional_types": "track"},
        )

    def current_user_saved_tracks(self, *, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        return self.request_json("GET", "/me/tracks", params={"limit": limit, "offset": offset})

    # -----------------
    # High-level helpers (fully paged)
    # -----------------

    def get_user_playlists(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        return self._paginate("/me/playlists", params={"limit": min(50, int(limit))}, page_key="items")

    def get_playlist_tracks(self, playlist_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        # Endpoint shape: {items: [{added_at, track: {...}}], total, ...}
        return self._paginate(
            f"/playlists/{playlist_id}/items",
            params={"limit": min(100, int(limit)), "additional_types": "track"},
            page_key="items",
        )

    def get_liked_songs(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        # Endpoint shape: {items: [{added_at, track: {...}}], total, ...}
        return self._paginate("/me/tracks", params={"limit": min(50, int(limit))}, page_key="items")
