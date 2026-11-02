import base64
import hashlib
import os
import tempfile
import unittest
from unittest import mock

# Ensure local imports work when running this file directly.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in os.sys.path:
    os.sys.path.insert(0, THIS_DIR)

from spotify_api.auth import SpotifyPKCEAuth, code_challenge_from_verifier, extract_code_from_redirect_url
from spotify_api.token_manager import TokenInfo, TokenManager
from spotify_api.data_loader import SpotifyDataLoader


class TestSpotifyAuthHelpers(unittest.TestCase):
    def test_code_challenge_matches_sha256_base64url_no_pad(self):
        verifier = "abc"
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest()).decode("utf-8").rstrip("=")
        self.assertEqual(code_challenge_from_verifier(verifier), expected)
        self.assertNotIn("=", code_challenge_from_verifier(verifier))

    def test_begin_oauth_flow_builds_authorize_url(self):
        config = {
            "spotify_client_id": "example-client-id",
            "spotify_redirect_uri": "http://localhost:8888/callback",
            "spotify_scopes": ["playlist-read-private"],
        }
        auth = SpotifyPKCEAuth(config, token_manager=TokenManager(cache_path=os.path.join(tempfile.gettempdir(), "spotify_token_test.json")))
        out = auth.begin_oauth_flow(show_dialog=True)
        self.assertIn("auth_url", out)
        self.assertIn("pkce_pair", out)
        self.assertIn("state", out)

        url = out["auth_url"]
        self.assertIn("accounts.spotify.com/authorize", url)
        self.assertIn("response_type=code", url)
        self.assertIn("code_challenge_method=S256", url)

    def test_extract_code_from_redirect_url(self):
        parsed = extract_code_from_redirect_url("http://localhost:8888/callback?code=AAA&state=BBB")
        self.assertEqual(parsed.get("code"), "AAA")
        self.assertEqual(parsed.get("state"), "BBB")


class TestSpotifyTokenManager(unittest.TestCase):
    def test_token_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            cache_path = os.path.join(td, "spotify_tokens.json")
            tm = TokenManager(cache_path=cache_path)
            cfg = {"spotify_cache_tokens": True}

            token = TokenInfo(access_token="at", token_type="Bearer", expires_at=9999999999.0, refresh_token="rt")
            self.assertTrue(tm.save(cfg, token))

            loaded = tm.load(cfg)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.access_token, "at")
            self.assertEqual(loaded.refresh_token, "rt")

    def test_save_writes_atomically_with_private_mode(self):
        with tempfile.TemporaryDirectory() as td:
            cache_path = os.path.join(td, "spotify_tokens.json")
            tm = TokenManager(cache_path=cache_path)
            token = TokenInfo(access_token="at", token_type="Bearer", expires_at=1.0)
            with mock.patch("spotify_api.token_manager.write_json_atomic") as writer:
                self.assertTrue(tm.save({"spotify_cache_tokens": True}, token))
            writer.assert_called_once_with(cache_path, token.to_dict(), mode=0o600)

            self.assertTrue(tm.save({"spotify_cache_tokens": True}, token))
            self.assertEqual(os.listdir(td), ["spotify_tokens.json"])
            if os.name != "nt":
                self.assertEqual(os.stat(cache_path).st_mode & 0o777, 0o600)

    def test_save_failure_is_logged(self):
        with tempfile.TemporaryDirectory() as td:
            tm = TokenManager(cache_path=os.path.join(td, "spotify_tokens.json"))
            token = TokenInfo(access_token="at", token_type="Bearer", expires_at=1.0)
            with mock.patch("spotify_api.token_manager.write_json_atomic", side_effect=OSError("disk full")), \
                 mock.patch("spotify_api.token_manager.log_warning") as warn:
                self.assertFalse(tm.save({"spotify_cache_tokens": True}, token))
            self.assertIn("disk full", warn.call_args[0][0])

    def test_corrupt_cache_load_is_logged(self):
        with tempfile.TemporaryDirectory() as td:
            cache_path = os.path.join(td, "spotify_tokens.json")
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write("{not json")
            tm = TokenManager(cache_path=cache_path)
            with mock.patch("spotify_api.token_manager.log_warning") as warn:
                self.assertIsNone(tm.load({"spotify_cache_tokens": True}))
            warn.assert_called_once()


class TestSpotifyNormalization(unittest.TestCase):
    def test_normalize_track_shape(self):
        sample = {
            "id": "123",
            "uri": "spotify:track:123",
            "name": "Song",
            "artists": [{"name": "A"}, {"name": "B"}],
            "album": {"name": "Album", "release_date": "2020-01-01"},
            "duration_ms": 180000,
            "explicit": False,
            "popularity": 42,
            "external_ids": {"isrc": "ISRC123"},
            "external_urls": {"spotify": "https://open.spotify.com/track/123"},
        }

        normalized = SpotifyDataLoader._normalize_track(sample)
        self.assertIsNotNone(normalized)
        assert normalized is not None

        self.assertEqual(normalized["track"], "Song")
        self.assertEqual(normalized["album"], "Album")
        self.assertEqual(normalized["spotify_id"], "123")
        self.assertEqual(normalized["release_date"], "2020-01-01")
        self.assertIn("A", normalized["artist"])
        self.assertIn("B", normalized["artist"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
