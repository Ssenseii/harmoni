"""Core-functionality tests for the Spotify "connect" path: credential validation
and the SpotifyClient HTTP layer (auth headers, pagination, retry/backoff,
rate-limit and token-refresh handling). No real network calls are made.
"""
import io
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in os.sys.path:
    os.sys.path.insert(0, THIS_DIR)
    os.sys.path.insert(0, os.path.dirname(THIS_DIR))

from spotify_api.auth import check_spotify_credentials, get_effective_spotify_client_id
from spotify_api.client import SpotifyClient
from spotify_api.token_manager import TokenInfo, TokenManager


def _make_response(body: dict, status: int = 200, headers: dict = None):
    resp = mock.MagicMock()
    resp.read.return_value = __import__("json").dumps(body).encode("utf-8")
    resp.status = status
    resp.headers = headers or {}
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def _make_client(tmp_dir, token=None):
    cfg = {
        "spotify_client_id": "test-client-id",
        "spotify_redirect_uri": "http://127.0.0.1:8888/callback",
        "spotify_max_retries": 2,
        "spotify_backoff_base": 0.0,
        "spotify_retry_jitter": 0.0,
    }
    tm = TokenManager(cache_path=os.path.join(tmp_dir, "tokens.json"))
    client = SpotifyClient(cfg, token_manager=tm)
    client.set_token(token or TokenInfo(
        access_token="AT", token_type="Bearer", expires_at=9999999999.0, refresh_token="RT"
    ))
    return client


class TestCheckSpotifyCredentials(unittest.TestCase):
    def test_missing_redirect_uri_is_not_ok(self):
        result = check_spotify_credentials({"spotify_client_id": "abc"})
        self.assertFalse(result["ok"])
        self.assertIn("spotify_redirect_uri", result["message"])

    def test_missing_client_id_is_not_ok_and_explains_setup(self):
        result = check_spotify_credentials({"spotify_redirect_uri": "http://127.0.0.1:8888/callback"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["client_id"], "")
        self.assertEqual(get_effective_spotify_client_id({}), "")
        message = result["message"]
        self.assertIn("https://developer.spotify.com/dashboard", message)
        self.assertIn("http://127.0.0.1:8888/callback", message)
        self.assertIn("Premium", message)
        self.assertIn("User Management", message)

    def test_configured_client_id_is_used_and_marked_ok(self):
        result = check_spotify_credentials({
            "spotify_client_id": "my-app-id",
            "spotify_redirect_uri": "http://127.0.0.1:8888/callback",
            "spotify_scopes": ["playlist-read-private"],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["client_id"], "my-app-id")
        self.assertEqual(result["client_id_source"], "config")


class TestSpotifyClientAuth(unittest.TestCase):
    def test_request_sends_bearer_token_header(self):
        with tempfile.TemporaryDirectory() as td:
            client = _make_client(td)
            with mock.patch("urllib.request.urlopen", return_value=_make_response({"id": "me"})) as urlopen:
                result = client.me()

            self.assertEqual(result, {"id": "me"})
            sent_request = urlopen.call_args[0][0]
            self.assertEqual(sent_request.get_header("Authorization"), "Bearer AT")

    def test_no_token_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {"spotify_client_id": "x", "spotify_redirect_uri": "http://127.0.0.1:8888/callback"}
            client = SpotifyClient(cfg, token_manager=TokenManager(cache_path=os.path.join(td, "tokens.json")))
            with self.assertRaises(RuntimeError):
                client.me()


class TestSpotifyClientRetryBehavior(unittest.TestCase):
    def test_429_retries_after_delay_then_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            client = _make_client(td)
            rate_limited = urllib.error.HTTPError(
                url="", code=429, msg="Too Many Requests",
                hdrs={"Retry-After": "0"}, fp=io.BytesIO(b""),
            )
            success = _make_response({"items": []})

            with mock.patch("urllib.request.urlopen", side_effect=[rate_limited, success]), \
                 mock.patch("time.sleep"):
                result = client.request_json("GET", "/me/playlists")

            self.assertEqual(result, {"items": []})

    def test_401_triggers_single_refresh_then_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            client = _make_client(td)
            unauthorized = urllib.error.HTTPError(
                url="", code=401, msg="Unauthorized", hdrs={}, fp=io.BytesIO(b""),
            )
            success = _make_response({"id": "me"})
            refreshed = TokenInfo(access_token="AT2", token_type="Bearer", expires_at=9999999999.0, refresh_token="RT")

            with mock.patch("urllib.request.urlopen", side_effect=[unauthorized, success]), \
                 mock.patch("spotify_api.client.SpotifyPKCEAuth.refresh_access_token", return_value=refreshed):
                result = client.me()

            self.assertEqual(result, {"id": "me"})
            self.assertEqual(client._token.access_token, "AT2")

    def test_exhausted_retries_raise_runtime_error(self):
        with tempfile.TemporaryDirectory() as td:
            client = _make_client(td)
            server_error = urllib.error.HTTPError(
                url="", code=503, msg="Unavailable", hdrs={}, fp=io.BytesIO(b""),
            )

            with mock.patch("urllib.request.urlopen", side_effect=server_error), \
                 mock.patch("time.sleep"):
                with self.assertRaises(RuntimeError):
                    client.request_json("GET", "/me")

    def test_non_retryable_4xx_raises_immediately_with_server_message(self):
        with tempfile.TemporaryDirectory() as td:
            client = _make_client(td)
            body = b'{"error": {"status": 404, "message": "Not found."}}'
            not_found = urllib.error.HTTPError(
                url="", code=404, msg="Not Found", hdrs={}, fp=io.BytesIO(body),
            )

            with mock.patch("urllib.request.urlopen", side_effect=not_found):
                with self.assertRaises(RuntimeError) as ctx:
                    client.request_json("GET", "/playlists/bad-id")

            self.assertIn("Not found.", str(ctx.exception))


class TestSpotifyClientPagination(unittest.TestCase):
    def test_get_user_playlists_follows_pages(self):
        with tempfile.TemporaryDirectory() as td:
            client = _make_client(td)
            page1 = _make_response({"items": [{"id": "1"}], "total": 2, "limit": 1, "offset": 0})
            page2 = _make_response({"items": [{"id": "2"}], "total": 2, "limit": 1, "offset": 1})

            with mock.patch("urllib.request.urlopen", side_effect=[page1, page2]):
                playlists = client.get_user_playlists(limit=1)

            self.assertEqual([p["id"] for p in playlists], ["1", "2"])

    def test_get_playlist_tracks_stops_when_no_more_items(self):
        with tempfile.TemporaryDirectory() as td:
            client = _make_client(td)
            empty_page = _make_response({"items": [], "total": 0})

            with mock.patch("urllib.request.urlopen", return_value=empty_page):
                tracks = client.get_playlist_tracks("playlist123")

            self.assertEqual(tracks, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
