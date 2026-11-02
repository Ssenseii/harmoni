"""Tests for playlist opening, queue guidance, failure reasons, Spotify setup help and sidebar quick actions."""
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(THIS_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton

app = QApplication.instance() or QApplication([])

from config import DEFAULT_CONFIG
from gui.dialogs import oauth_dialog, queued_notice
from gui.views import spotify_view as spotify_view_module
from gui.views import youtube_view as youtube_view_module
from gui.views.downloads_view import DownloadsView
from gui.workers.download_queue import DownloadQueue, DownloadStatus


def _spotify_view(test, queue=None):
    """Build a SpotifyView with no cached token and two loaded playlists.

    @param test: Test case that owns cleanup.
    @param queue: Optional queue, a MagicMock by default.
    """
    with mock.patch.object(spotify_view_module.SpotifyPKCEAuth, "load_cached_token", return_value=None):
        view = spotify_view_module.SpotifyView({"spotify_cache_tokens": False}, queue or mock.MagicMock())
    test.addCleanup(view.deleteLater)
    view._on_playlists_loaded([
        {"id": "a", "name": "A", "tracks_total": 3, "fetchable": True},
        {"id": "b", "name": "B", "tracks_total": 4, "fetchable": True},
    ])
    return view


class TestPlaylistClick(unittest.TestCase):
    def setUp(self):
        self.view = _spotify_view(self)

    def test_plain_click_opens_playlist(self):
        with mock.patch.object(spotify_view_module, "SpotifyWorker") as worker_cls:
            self.view.playlist_list.itemClicked.emit(self.view.playlist_list.item(0))
        worker_cls.return_value.fetch_playlist_tracks.assert_called_once_with("a", "A")

    def test_ctrl_click_only_selects(self):
        with mock.patch.object(spotify_view_module, "SpotifyWorker") as worker_cls, \
             mock.patch.object(spotify_view_module.QApplication, "keyboardModifiers", return_value=Qt.ControlModifier):
            self.view.playlist_list.itemClicked.emit(self.view.playlist_list.item(0))
        worker_cls.assert_not_called()

    def test_double_click_does_not_restart_a_running_load(self):
        with mock.patch.object(spotify_view_module, "SpotifyWorker") as worker_cls:
            worker_cls.return_value.isRunning.return_value = True
            item = self.view.playlist_list.item(0)
            self.view.playlist_list.itemClicked.emit(item)
            self.view.playlist_list.itemDoubleClicked.emit(item)
        self.assertEqual(worker_cls.call_count, 1)
        worker_cls.return_value.cancel.assert_not_called()


class TestQueuedNotice(unittest.TestCase):
    def test_says_downloads_need_start(self):
        self.assertIn("Start Downloads", queued_notice.QUEUED_HINT)

    def test_spotify_add_offers_downloads(self):
        view = _spotify_view(self)
        view.current_tracks = [{"artist": "X", "track": "Y"}]
        opened = []
        view.navigate_to.connect(opened.append)
        with mock.patch.object(spotify_view_module.queued_notice, "confirm_queued", return_value=True) as confirm:
            view._add_single_to_queue(0)
        confirm.assert_called_once()
        self.assertEqual(opened, ["downloads"])

    def test_youtube_add_offers_downloads(self):
        view = youtube_view_module.YouTubeView({}, DownloadQueue())
        self.addCleanup(view.deleteLater)
        opened = []
        view.navigate_to.connect(opened.append)
        view.url_input.setText("Artist - Song")
        with mock.patch.object(youtube_view_module, "confirm_queued", return_value=True):
            view._add_single_to_queue()
        self.assertEqual(opened, ["downloads"])


class TestDownloadsDetails(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = DownloadQueue()
        self.view = DownloadsView({"output_dir": self.tmp.name}, self.queue)
        self.addCleanup(self.view.deleteLater)

    def test_failed_row_shows_reason(self):
        item = self.queue.add_track("Artist", "Song")
        self.queue.update_item_status(item.id, DownloadStatus.FAILED, error_message="No search result matched the track length.")
        self.assertIsNone(self.view.table.cellWidget(0, 4))
        self.assertEqual(self.view.table.item(0, 4).text(), "No search result matched the track length.")

    def test_retry_brings_progress_bar_back(self):
        item = self.queue.add_track("Artist", "Song")
        self.queue.update_item_status(item.id, DownloadStatus.FAILED, error_message="boom")
        self.view._retry_failed()
        self.assertIsNotNone(self.view.table.cellWidget(0, 4))
        self.assertIsNone(self.view.table.item(0, 4))

    def test_waiting_hint_until_started(self):
        self.queue.add_track("Artist", "Song")
        self.assertFalse(self.view.waiting_label.isHidden())
        self.assertIn("Press Start Downloads", self.view.waiting_label.text())
        self.view.worker = mock.Mock()
        self.view._update_waiting_hint()
        self.assertTrue(self.view.waiting_label.isHidden())


class TestSpotifySetupDialog(unittest.TestCase):
    def test_shows_and_copies_redirect_uri(self):
        dialog = oauth_dialog.SpotifySetupDialog("http://127.0.0.1:9999/callback")
        self.addCleanup(dialog.deleteLater)
        field = dialog.findChild(QLineEdit)
        self.assertEqual(field.text(), "http://127.0.0.1:9999/callback")
        copy_btn = next(b for b in dialog.findChildren(QPushButton) if b.text() == "Copy")
        copy_btn.click()
        self.assertEqual(QApplication.clipboard().text(), "http://127.0.0.1:9999/callback")

    def test_prompt_returns_true_for_open_settings(self):
        with mock.patch.object(oauth_dialog.SpotifySetupDialog, "exec", return_value=QDialog.Accepted):
            self.assertTrue(oauth_dialog.prompt_spotify_setup(None, ""))
        with mock.patch.object(oauth_dialog.SpotifySetupDialog, "exec", return_value=QDialog.Rejected):
            self.assertFalse(oauth_dialog.prompt_spotify_setup(None, ""))


class TestSidebarQuickActions(unittest.TestCase):
    def setUp(self):
        from gui.main_window import MainWindow

        with mock.patch("gui.main_window.AppUpdateCheckWorker.start"), \
             mock.patch("gui.views.spotify_view.SpotifyPKCEAuth.load_cached_token", return_value=None):
            self.window = MainWindow(dict(DEFAULT_CONFIG))
        self.addCleanup(self.window.deleteLater)
        self.queue = self.window.download_queue

    def test_buttons_follow_queue(self):
        self.assertFalse(self.window.quick_start_btn.isEnabled())
        item = self.queue.add_track("Artist", "Song")
        self.assertEqual(self.window.quick_start_btn.text(), "Start Downloads (1)")
        self.assertTrue(self.window.quick_start_btn.isEnabled())
        self.queue.update_item_status(item.id, DownloadStatus.FAILED, error_message="boom")
        self.assertEqual(self.window.quick_retry_btn.text(), "Retry Failed (1)")
        self.assertTrue(self.window.quick_retry_btn.isEnabled())

    def test_start_opens_downloads_and_starts(self):
        self.queue.add_track("Artist", "Song")
        with mock.patch.object(self.window.downloads_view, "_start_downloads") as start:
            self.window.quick_start_btn.click()
        start.assert_called_once()
        self.assertIs(self.window.view_stack.currentWidget(), self.window.downloads_view)

    def test_spotify_settings_focuses_client_id(self):
        with mock.patch.object(self.window.settings_view, "focus_spotify_client_id") as focus:
            self.window._navigate_to_view("spotify_settings")
        focus.assert_called_once()
        self.assertIs(self.window.view_stack.currentWidget(), self.window.settings_view)


if __name__ == "__main__":
    unittest.main()
