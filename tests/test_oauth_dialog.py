"""Tests for the Spotify OAuth dialog: callback handler, server lifecycle, busy port and token exchange thread."""
import os
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
if ROOT_DIR not in os.sys.path:
    os.sys.path.insert(0, ROOT_DIR)

from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

from gui.dialogs import oauth_dialog
from gui.dialogs.oauth_dialog import CallbackServerThread, SpotifyOAuthDialog
from spotify_api.token_manager import TokenInfo


def _free_port():
    """Return a loopback port that is free right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_is_free(port):
    """Return True when a plain socket can bind the loopback port.

    @param port: Port to probe.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def _get(url):
    """GET a URL and return (status, body text) without raising on HTTP errors.

    @param url: Address to fetch.
    """
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def _config(port):
    """Return a dialog config pointing the redirect at the given port.

    @param port: Loopback port for the callback.
    """
    return {
        "spotify_client_id": "test-client-id",
        "spotify_redirect_uri": f"http://127.0.0.1:{port}/callback",
        "spotify_scopes": ["playlist-read-private"],
        "spotify_cache_tokens": False,
    }


class TestCallbackHandler(unittest.TestCase):
    def setUp(self):
        self.port = _free_port()
        self.thread = CallbackServerThread(self.port, "/callback")
        self.received = []
        self.thread.callback_received.connect(self.received.append)
        self.thread.bind()
        self.thread.start()

    def tearDown(self):
        self.thread.stop()
        self.thread.wait(3000)

    def test_other_paths_get_404_and_do_not_complete(self):
        status, _ = _get(f"http://127.0.0.1:{self.port}/favicon.ico")
        self.assertEqual(status, 404)
        time.sleep(0.3)
        self.assertEqual(self.received, [])
        self.assertTrue(self.thread.isRunning())

    def test_error_query_shows_failure_page_and_reports_it(self):
        status, body = _get(f"http://127.0.0.1:{self.port}/callback?error=access_denied&state=s")
        self.assertEqual(status, 200)
        self.assertIn("Authentication Failed", body)
        self.assertIn("access_denied", body)
        self.assertTrue(self.thread.wait(3000))
        APP.processEvents()
        self.assertEqual(len(self.received), 1)
        self.assertIn("error=access_denied", self.received[0])

    def test_code_on_callback_path_completes(self):
        status, body = _get(f"http://127.0.0.1:{self.port}/callback?code=abc&state=s")
        self.assertEqual(status, 200)
        self.assertIn("Authentication Successful", body)
        self.assertTrue(self.thread.wait(3000))
        APP.processEvents()
        self.assertEqual(self.received, [f"http://127.0.0.1:{self.port}/callback?code=abc&state=s"])


class TestDialogLifecycle(unittest.TestCase):
    def test_reject_stops_server_thread_and_frees_port(self):
        port = _free_port()
        dialog = SpotifyOAuthDialog(_config(port))
        with mock.patch.object(oauth_dialog.webbrowser, "open") as browser:
            dialog._start_oauth()
        browser.assert_called_once()
        thread = dialog.callback_thread
        self.assertIsNotNone(thread)
        self.assertTrue(thread.isRunning())
        self.assertFalse(_port_is_free(port))

        dialog.reject()

        self.assertFalse(thread.isRunning())
        self.assertIsNone(dialog.callback_thread)
        self.assertTrue(_port_is_free(port))
        dialog.deleteLater()

    def test_busy_port_shows_message_and_manual_fallback(self):
        port = _free_port()
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", port))
        holder.listen(1)
        try:
            dialog = SpotifyOAuthDialog(_config(port))
            with mock.patch.object(oauth_dialog.webbrowser, "open"):
                dialog._start_oauth()
            text = dialog.status_label.text()
            self.assertIn(f"Port {port} is already in use", text)
            self.assertIn("paste the redirect URL manually", text)
            self.assertIsNone(dialog.callback_thread)
            dialog.reject()
            dialog.deleteLater()
        finally:
            holder.close()

    def test_missing_client_id_never_opens_browser(self):
        config = _config(_free_port())
        config["spotify_client_id"] = ""
        dialog = SpotifyOAuthDialog(config)
        requested = []
        dialog.open_settings_requested.connect(lambda: requested.append(True))
        with mock.patch.object(oauth_dialog.webbrowser, "open") as browser, \
             mock.patch.object(oauth_dialog, "prompt_spotify_setup", return_value=True) as prompt:
            dialog._start_oauth()
        browser.assert_not_called()
        prompt.assert_called_once()
        self.assertIn("User Management", prompt.call_args[0][1])
        self.assertEqual(requested, [True])
        self.assertIsNone(dialog.callback_thread)
        dialog.deleteLater()


class TestTokenExchangeThread(unittest.TestCase):
    def test_exchange_runs_off_the_ui_thread(self):
        dialog = SpotifyOAuthDialog(_config(_free_port()))
        flow = dialog.auth.begin_oauth_flow()
        dialog.pkce_pair = flow["pkce_pair"]
        dialog.state = flow["state"]
        threads = []
        results = []
        dialog.auth_completed.connect(lambda ok, msg: results.append(ok))

        def fake_exchange(*, code, code_verifier):
            threads.append(threading.current_thread())
            return TokenInfo(access_token="AT", token_type="Bearer", expires_at=9999999999.0)

        with mock.patch.object(dialog.auth, "exchange_code_for_token", side_effect=fake_exchange), \
             mock.patch.object(oauth_dialog.QTimer, "singleShot"):
            dialog._process_callback_url(f"http://127.0.0.1/callback?code=abc&state={dialog.state}")
            dialog._exchange_thread.wait(5000)
            APP.processEvents()

        self.assertEqual(len(threads), 1)
        self.assertIsNot(threads[0], threading.main_thread())
        self.assertEqual(results, [True])
        dialog.deleteLater()

    def test_exchange_failure_is_reported(self):
        dialog = SpotifyOAuthDialog(_config(_free_port()))
        flow = dialog.auth.begin_oauth_flow()
        dialog.pkce_pair = flow["pkce_pair"]
        dialog.state = flow["state"]
        results = []
        dialog.auth_completed.connect(lambda ok, msg: results.append((ok, msg)))
        with mock.patch.object(dialog.auth, "exchange_code_for_token", side_effect=RuntimeError("bad code")):
            dialog._process_callback_url(f"http://127.0.0.1/callback?code=abc&state={dialog.state}")
            dialog._exchange_thread.wait(5000)
            APP.processEvents()
        self.assertEqual(results, [(False, "bad code")])
        self.assertIn("bad code", dialog.status_label.text())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
