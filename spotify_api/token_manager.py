import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from utils.jsonio import write_json_atomic
from utils.logger import log_warning


def _get_default_cache_path():
    """Resolve token cache path relative to the app directory, not the working directory."""
    try:
        import sys
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        base = "."
    return os.path.join(base, "data", "spotify_tokens.json")

DEFAULT_TOKEN_CACHE_PATH = _get_default_cache_path()


@dataclass(frozen=True)
class TokenInfo:
    """Canonical token payload stored by TokenManager."""

    access_token: str
    token_type: str
    expires_at: float
    refresh_token: Optional[str] = None
    scope: Optional[str] = None

    @staticmethod
    def from_spotify_token_response(payload: Dict[str, Any], *, now: Optional[float] = None) -> "TokenInfo":
        """Convert Spotify token response JSON into TokenInfo.

        Spotify returns:
        - access_token
        - token_type
        - expires_in (seconds)
        - refresh_token (optional)
        - scope (space-delimited string)
        """

        now_ts = float(time.time() if now is None else now)
        expires_in = float(payload.get("expires_in", 0))

        return TokenInfo(
            access_token=str(payload.get("access_token", "")),
            token_type=str(payload.get("token_type", "Bearer")),
            expires_at=now_ts + expires_in,
            refresh_token=payload.get("refresh_token"),
            scope=payload.get("scope"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "expires_at": self.expires_at,
            "refresh_token": self.refresh_token,
            "scope": self.scope,
        }


class TokenManager:
    """Handles optional token caching and basic expiry logic."""

    def __init__(self, *, cache_path: str = DEFAULT_TOKEN_CACHE_PATH):
        self.cache_path = cache_path

    def should_cache(self, config: Dict[str, Any]) -> bool:
        return bool((config or {}).get("spotify_cache_tokens", True))

    def ensure_cache_dir(self) -> None:
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)

    def load(self, config: Dict[str, Any]) -> Optional[TokenInfo]:
        """Load cached token info from disk if enabled and present."""
        if not self.should_cache(config):
            return None

        if not os.path.exists(self.cache_path):
            return None

        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log_warning(f"Could not read the Spotify token cache at {self.cache_path}: {e}")
            return None

        try:
            return TokenInfo(
                access_token=str(data.get("access_token", "")),
                token_type=str(data.get("token_type", "Bearer")),
                expires_at=float(data.get("expires_at", 0)),
                refresh_token=data.get("refresh_token"),
                scope=data.get("scope"),
            )
        except Exception as e:
            log_warning(f"The Spotify token cache at {self.cache_path} has an unexpected shape: {e}")
            return None

    def save(self, config: Dict[str, Any], token: TokenInfo) -> bool:
        """Persist token info to disk if enabled."""
        if not self.should_cache(config):
            return False

        try:
            write_json_atomic(self.cache_path, token.to_dict(), mode=0o600)
            return True
        except Exception as e:
            log_warning(f"Could not save the Spotify token cache to {self.cache_path}: {e}")
            return False

    def clear(self) -> bool:
        try:
            if os.path.exists(self.cache_path):
                os.remove(self.cache_path)
            return True
        except Exception as e:
            log_warning(f"Could not remove the Spotify token cache at {self.cache_path}: {e}")
            return False

    @staticmethod
    def is_expired(token: TokenInfo, *, skew_seconds: int = 60) -> bool:
        return time.time() >= float(token.expires_at) - float(skew_seconds)
