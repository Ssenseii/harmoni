"""Tests for the missing Client ID guard, typed Spotify errors, the 429 cap and the view's error mapping."""
import glob
import io
import os
import tempfile
import threading
import unittest
import urllib.error
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
if ROOT_DIR not in os.sys.path:
    os.sys.path.insert(0, ROOT_DIR)

from PySide6.QtWidgets import QApplication

from spotify_api import auth as auth_module
from spotify_api.auth import SpotifyPKCEAuth
from spotify_api.client import NETWORK_ERROR_STATUS, SpotifyAPIError, SpotifyClient
from spotify_api.token_manager import TokenInfo, TokenManager

APP = QApplication.instance() or QApplication([])

from gui.views import spotify_view as spotify_view_module
from gui.views.spotify_view import SpotifyView, spotify_error_feedback
from gui.workers.spotify_worker import SpotifyWorker
import menus.downloads_menu as downloads_menu


def _client(tmp_dir, **overrides):
    """Build a SpotifyClient with a valid cached token and no retry delays.

    @param tmp_dir: Directory for the token cache.
    @param overrides: Extra config keys.
    """
    cfg = {
        "spotify_client_id": "test-client-id",
        "spotify_redirect_uri": "http://127.0.0.1:8888/callback",
        "spotify_max_retries": 2,
        "spotify_backoff_base": 0.0,
        "spotify_retry_jitter": 0.0,
    }
    cfg.update(overrides)
    client = SpotifyClient(cfg, token_manager=TokenManager(cache_path=os.path.join(tmp_dir, "tokens.json")))
    client.set_token(TokenInfo(access_token="AT", token_type="Bearer", expires_at=9999999999.0, refresh_token="RT"))
    return client


def _http_error(code, body=b"", headers=None):
    """Build an HTTPError like urllib raises.

    @param code: HTTP status.
    @param body: Response body bytes.
    @param headers: Response headers.
    """
    return urllib.error.HTTPError(url="", code=code, msg="x", hdrs=headers or {}, fp=io.BytesIO(body))


class TestMissingClientId(unittest.TestCase):
    def test_authorize_url_raises_without_client_id(self):
        auth = SpotifyPKCEAuth({"spotify_redirect_uri": "http://127.0.0.1:8888/callback"})
        with self.assertRaises(ValueError):
            auth.get_authorize_url(code_challenge="abc")
        with self.assertRaises(ValueError):
            auth.begin_oauth_flow()

    def test_no_shared_client_id_left_in_spotify_api(self):
        needle = "d99b082b" + "01d74d61"
        package_dir = os.path.dirname(auth_module.__file__)
        for path in glob.glob(os.path.join(package_dir, "*.py")):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertNotIn(needle, text, path)
            self.assertNotIn("EXPORTIFY_FALLBACK", text, path)


class TestTypedErrors(unittest.TestCase):
    def test_http_error_carries_status_and_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            client = _client(td)
            body = b'{"error": {"status": 403, "message": "Forbidden"}}'
            with mock.patch("urllib.request.urlopen", side_effect=_http_error(403, body)):
                with self.assertRaises(SpotifyAPIError) as ctx:
                    client.request_json("GET", "/playlists/x/items")
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.endpoint, "GET /playlists/x/items")
        self.assertEqual(ctx.exception.message, "Forbidden")
        self.assertIsInstance(ctx.exception, RuntimeError)

    def test_network_failure_has_network_status(self):
        with tempfile.TemporaryDirectory() as td:
            client = _client(td)
            with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")), \
                 mock.patch("time.sleep"):
                with self.assertRaises(SpotifyAPIError) as ctx:
                    client.me()
        self.assertEqual(ctx.exception.status, NETWORK_ERROR_STATUS)

    def test_token_endpoint_error_is_typed(self):
        response = mock.MagicMock(status_code=400, text='{"error":"invalid_grant"}')
        http_client = mock.MagicMock()
        http_client.__enter__.return_value.post.return_value = response
        auth = SpotifyPKCEAuth({"spotify_client_id": "id"}, token_manager=mock.MagicMock())
        with mock.patch.object(auth_module.httpx, "Client", return_value=http_client):
            with self.assertRaises(SpotifyAPIError) as ctx:
                auth.refresh_access_token(refresh_token="RT")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.endpoint, "POST /api/token")


class TestRetryAfterCap(unittest.TestCase):
    def _sleep_for(self, retry_after, **overrides):
        """Return the delay slept for one 429 with the given Retry-After.

        @param retry_after: Retry-After header value.
        @param overrides: Extra config keys.
        """
        with tempfile.TemporaryDirectory() as td:
            client = _client(td, **overrides)
            ok = mock.MagicMock()
            ok.read.return_value = b"{}"
            ok.status = 200
            ok.headers = {}
            ok.__enter__.return_value = ok
            with mock.patch("urllib.request.urlopen", side_effect=[_http_error(429, headers={"Retry-After": retry_after}), ok]), \
                 mock.patch("time.sleep") as sleep:
                client.request_json("GET", "/me")
        return sleep.call_args[0][0]

    def test_huge_retry_after_is_capped_at_30_seconds(self):
        self.assertEqual(self._sleep_for("86400"), 30.0)

    def test_cap_is_configurable(self):
        self.assertEqual(self._sleep_for("86400", spotify_max_retry_after=5), 5.0)

    def test_small_retry_after_is_honoured(self):
        self.assertEqual(self._sleep_for("3"), 3.0)


class TestErrorFeedbackMapping(unittest.TestCase):
    def test_401_reconnects(self):
        self.assertEqual(spotify_error_feedback(401, "expired")[0], "reconnect")

    def test_403_explains_development_mode(self):
        action, _, text = spotify_error_feedback(403, "Forbidden")
        self.assertEqual(action, "warn")
        self.assertIn("Premium", text)
        self.assertIn("User Management", text)
        self.assertIn("playlist", text)

    def test_429_is_rate_limit(self):
        action, title, _ = spotify_error_feedback(429, "Too many")
        self.assertEqual(action, "warn")
        self.assertIn("Rate Limit", title)

    def test_network_error_warns_without_reconnect(self):
        action, _, text = spotify_error_feedback(NETWORK_ERROR_STATUS, "token request failed: offline")
        self.assertEqual(action, "warn")
        self.assertIn("try again", text)

    def test_message_with_token_word_does_not_force_reconnect(self):
        self.assertEqual(spotify_error_feedback(500, "token oops expired")[0], "warn")


class TestSpotifyViewErrors(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        cache_path = os.path.join(self._tmp.name, "tokens.json")
        TokenManager(cache_path=cache_path).save(
            {}, TokenInfo(access_token="AT", token_type="Bearer", expires_at=9999999999.0, refresh_token="RT")
        )
        real_tm = TokenManager
        patches = [
            mock.patch("spotify_api.auth.TokenManager", lambda: real_tm(cache_path=cache_path)),
            mock.patch.object(SpotifyView, "_refresh_playlists", lambda self: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.view = SpotifyView({"spotify_client_id": "id", "spotify_redirect_uri": "http://127.0.0.1:8888/callback"}, mock.MagicMock())
        self.assertEqual(self.view.status_label.text(), "Connected")

    def tearDown(self):
        self.view.deleteLater()
        self._tmp.cleanup()

    def test_network_error_keeps_user_connected(self):
        with mock.patch.object(spotify_view_module.QMessageBox, "warning") as warning, \
             mock.patch.object(self.view, "_prompt_reconnect") as reconnect:
            self.view._on_error(NETWORK_ERROR_STATUS, "Spotify token request failed: offline")
        reconnect.assert_not_called()
        warning.assert_called_once()
        self.assertEqual(self.view.status_label.text(), "Connected")

    def test_403_shows_guidance_and_stays_connected(self):
        with mock.patch.object(spotify_view_module.QMessageBox, "warning") as warning:
            self.view._on_error(403, "Forbidden")
        self.assertIn("User Management", warning.call_args[0][2])
        self.assertEqual(self.view.status_label.text(), "Connected")

    def test_401_disconnects_and_prompts(self):
        with mock.patch.object(self.view, "_prompt_reconnect") as reconnect:
            self.view._on_error(401, "Unauthorized")
        reconnect.assert_called_once()
        self.assertEqual(self.view.status_label.text(), "Not connected")

    def test_connect_without_client_id_never_opens_dialog_or_browser(self):
        self.view.config = {"spotify_redirect_uri": "http://127.0.0.1:8888/callback"}
        with mock.patch("gui.dialogs.oauth_dialog.prompt_spotify_setup", return_value=True) as prompt, \
             mock.patch.object(spotify_view_module, "SpotifyOAuthDialog") as dialog_cls, \
             mock.patch("webbrowser.open") as browser, \
             mock.patch.object(self.view, "_open_settings") as open_settings:
            self.view._show_oauth_dialog()
        prompt.assert_called_once()
        self.assertIn("User Management", prompt.call_args[0][1])
        dialog_cls.assert_not_called()
        browser.assert_not_called()
        open_settings.assert_called_once()

    def test_open_settings_emits_navigation(self):
        seen = []
        self.view.navigate_to.connect(seen.append)
        self.view._open_settings()
        self.assertEqual(seen, ["settings"])


class TestStartupRefreshOffUiThread(unittest.TestCase):
    def test_expired_token_refreshes_on_a_worker_thread(self):
        with tempfile.TemporaryDirectory() as td:
            cache_path = os.path.join(td, "tokens.json")
            TokenManager(cache_path=cache_path).save(
                {}, TokenInfo(access_token="AT", token_type="Bearer", expires_at=1.0, refresh_token="RT")
            )
            real_tm = TokenManager
            threads = []

            def fake_refresh(self, *, refresh_token):
                threads.append(threading.current_thread())
                return TokenInfo(access_token="AT2", token_type="Bearer", expires_at=9999999999.0)

            with mock.patch("spotify_api.auth.TokenManager", lambda: real_tm(cache_path=cache_path)), \
                 mock.patch.object(SpotifyPKCEAuth, "refresh_access_token", fake_refresh), \
                 mock.patch.object(SpotifyView, "_refresh_playlists", lambda self: None):
                view = SpotifyView({"spotify_client_id": "id"}, mock.MagicMock())
                view._refresh_thread.wait(5000)
                APP.processEvents()
                self.assertEqual(len(threads), 1)
                self.assertIsNot(threads[0], threading.main_thread())
                self.assertEqual(view.status_label.text(), "Connected")
                view.deleteLater()


class TestWorkerErrorStatus(unittest.TestCase):
    def _run_worker(self, error):
        """Run the playlists task synchronously with the client raising error and return emitted statuses.

        @param error: Exception raised by the client call.
        """
        client = mock.Mock()
        client.current_user_playlists.side_effect = error
        worker = SpotifyWorker({}, client=client)
        worker._task = "playlists"
        seen = []
        worker.error_status.connect(lambda status, message: seen.append((status, message)))
        worker.run()
        return seen

    def test_api_error_status_is_forwarded(self):
        seen = self._run_worker(SpotifyAPIError(403, "GET /me/playlists", "Forbidden"))
        self.assertEqual(seen[0][0], 403)

    def test_unknown_error_has_negative_status(self):
        seen = self._run_worker(ValueError("boom"))
        self.assertEqual(seen[0][0], -1)


class TestCliCredentialGuard(unittest.TestCase):
    def test_authenticate_stops_before_auth_without_client_id(self):
        cfg = {"spotify_redirect_uri": "http://127.0.0.1:8888/callback"}
        with mock.patch.object(SpotifyPKCEAuth, "begin_oauth_flow") as begin, \
             mock.patch.object(downloads_menu.webbrowser, "open") as browser, \
             mock.patch.object(downloads_menu, "log_info"), \
             mock.patch.object(downloads_menu, "log_warning") as warn:
            downloads_menu._spotify_authenticate(cfg)
        begin.assert_not_called()
        browser.assert_not_called()
        self.assertTrue(any("User Management" in str(c) for c in warn.call_args_list))

    def test_authenticate_prints_setup_message_once(self):
        cfg = {"spotify_redirect_uri": "http://127.0.0.1:8888/callback"}
        with mock.patch.object(downloads_menu, "log_info") as info, \
             mock.patch.object(downloads_menu, "log_warning") as warn:
            downloads_menu._spotify_authenticate(cfg)
        message = auth_module.check_spotify_credentials(cfg)["message"]
        printed = [str(c[0][0]) for c in info.call_args_list + warn.call_args_list]
        self.assertEqual(printed.count(message), 1)

    def test_setup_help_uses_loopback_default_redirect(self):
        with mock.patch.object(downloads_menu, "log_info") as info, \
             mock.patch.object(downloads_menu, "log_warning"):
            downloads_menu._spotify_setup_help({"spotify_redirect_uri": ""})
        text = "\n".join(str(c[0][0]) for c in info.call_args_list)
        self.assertIn("http://127.0.0.1:8888/callback", text)
        self.assertNotIn("http://localhost", text)
        self.assertNotIn("Exportify", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
