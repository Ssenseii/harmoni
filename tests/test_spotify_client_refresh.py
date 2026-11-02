"""Tests for SpotifyClient token refresh when several threads share one client."""
import os
import sys
import threading
import time
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(THIS_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from spotify_api.client import SpotifyClient
from spotify_api.token_manager import TokenInfo


class TestSharedClientRefresh(unittest.TestCase):
    def test_concurrent_get_token_refreshes_once(self):
        expired = TokenInfo(access_token="old", token_type="Bearer", expires_at=0.0, refresh_token="R1")
        fresh = TokenInfo(access_token="new", token_type="Bearer", expires_at=time.time() + 3600, refresh_token="R2")
        client = SpotifyClient({"spotify_cache_tokens": False}, token_manager=mock.Mock(is_expired=lambda t: t.expires_at < time.time()))
        client._token = expired
        calls = []

        def slow_refresh(self_auth, *, refresh_token):
            calls.append(refresh_token)
            time.sleep(0.2)
            return fresh

        results = []
        with mock.patch("spotify_api.client.SpotifyPKCEAuth.refresh_access_token", slow_refresh):
            threads = [threading.Thread(target=lambda: results.append(client.get_token())) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(5)
        self.assertEqual(calls, ["R1"])
        self.assertEqual([r.access_token for r in results], ["new", "new"])


if __name__ == "__main__":
    unittest.main()
