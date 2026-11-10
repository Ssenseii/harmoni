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
from gui import notices
from gui.dialogs import oauth_dialog
from gui.views import spotify_view as spotify_view_module
from gui.views import youtube_view as youtube_view_module
from gui.views.downloads_view import DownloadsView
from gui.workers.download_queue import DownloadQueue, DownloadStatus


def capture_notices(test):
    """Record every notice posted during a test as (text, kind, action_label, action).

    @param test: Test case that owns the cleanup.
    """
    seen = []

    def record(*notice):
        seen.append(notice)

    notices.hub.posted.connect(record)
    test.addCleanup(notices.hub.posted.disconnect, record)
    return seen


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
    def _assert_queued_notice(self, seen, opened):
        """Check the notice says downloads wait for Start and its button opens Downloads.

        @param seen: Notices captured during the test.
        @param opened: Views the view asked to navigate to.
        """
        [(text, kind, label, action)] = seen
        self.assertIn(notices.QUEUED_HINT, text)
        self.assertEqual((kind, label), ("success", "Go to Downloads"))
        action()
        self.assertEqual(opened, ["downloads"])

    def test_spotify_add_posts_notice_without_blocking(self):
        view = _spotify_view(self)
        view.current_tracks = [{"artist": "X", "track": "Y"}]
        opened = []
        view.navigate_to.connect(opened.append)
        seen = capture_notices(self)
        view._add_single_to_queue(0)
        self._assert_queued_notice(seen, opened)

    def test_youtube_add_posts_notice_without_blocking(self):
        view = youtube_view_module.YouTubeView({}, DownloadQueue())
        self.addCleanup(view.deleteLater)
        opened = []
        view.navigate_to.connect(opened.append)
        seen = capture_notices(self)
        view.url_input.setText("Artist - Song")
        view._add_single_to_queue()
        self._assert_queued_notice(seen, opened)

    def test_download_complete_offers_retry(self):
        view = DownloadsView({}, DownloadQueue())
        self.addCleanup(view.deleteLater)
        seen = capture_notices(self)
        with mock.patch.object(view, "_retry_failed") as retry:
            view._on_queue_completed(2, 1)
            [(text, kind, label, action)] = seen
            action()
        self.assertEqual((kind, label), ("warning", "Retry Failed"))
        retry.assert_called_once()


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


class TestNoticeBar(unittest.TestCase):
    def setUp(self):
        from gui.main_window import MainWindow

        with mock.patch("gui.main_window.AppUpdateCheckWorker.start"), \
             mock.patch("gui.views.spotify_view.SpotifyPKCEAuth.load_cached_token", return_value=None):
            self.window = MainWindow(dict(DEFAULT_CONFIG))
        self.addCleanup(self.window.deleteLater)

    def test_notice_shows_and_runs_action(self):
        clicked = []
        notices.notify("Added 3 tracks.", "success", "Go to Downloads", lambda: clicked.append(True))
        self.assertFalse(self.window.notice_bar.isHidden())
        self.assertEqual(self.window.notice_label.text(), "Added 3 tracks.")
        self.window.notice_action_btn.click()
        self.assertEqual(clicked, [True])
        self.assertTrue(self.window.notice_bar.isHidden())

    def test_notice_without_action_hides_button_and_times_out(self):
        notices.notify("Settings saved.", "success")
        self.assertTrue(self.window.notice_action_btn.isHidden())
        self.assertTrue(self.window._notice_timer.isActive())
        self.window._notice_timer.timeout.emit()
        self.assertTrue(self.window.notice_bar.isHidden())


class TestSettingsScrolling(unittest.TestCase):
    def test_combo_ignores_wheel_until_focused(self):
        from PySide6.QtCore import QPoint, QPointF
        from PySide6.QtGui import QWheelEvent
        from gui.views.settings_view import ScrollSafeComboBox

        combo = ScrollSafeComboBox()
        self.addCleanup(combo.deleteLater)
        combo.addItems(["mp3", "flac", "m4a"])
        event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120),
                            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        combo.wheelEvent(event)
        self.assertEqual(combo.currentIndex(), 0)
        self.assertFalse(event.isAccepted())

    def test_save_bar_sits_outside_the_scroll_area(self):
        from PySide6.QtWidgets import QPushButton, QScrollArea
        from gui.views.settings_view import SettingsView

        with mock.patch("gui.views.settings_view.YtdlpStatusWorker"):
            view = SettingsView(dict(DEFAULT_CONFIG))
        self.addCleanup(view.deleteLater)
        scroll = view.findChild(QScrollArea)
        save = next(b for b in view.findChildren(QPushButton) if b.text() == "Save Settings")
        self.assertFalse(scroll.isAncestorOf(save))


class TestStatusBar(unittest.TestCase):
    def test_matches_spotify_connected_at_startup(self):
        from gui.main_window import MainWindow
        from spotify_api.token_manager import TokenInfo

        token = TokenInfo(access_token="AT", token_type="Bearer", expires_at=9999999999.0)
        with mock.patch("gui.main_window.AppUpdateCheckWorker.start"), \
             mock.patch("gui.views.spotify_view.SpotifyPKCEAuth.load_cached_token", return_value=token), \
             mock.patch("gui.views.spotify_view.SpotifyWorker"):
            window = MainWindow(dict(DEFAULT_CONFIG))
        self.addCleanup(window.deleteLater)
        self.assertTrue(window.spotify_view.is_connected)
        self.assertEqual(window.title_bar.spotify_chip.label.text(), "Spotify: Connected")


class TestTitleBarChips(unittest.TestCase):
    def setUp(self):
        from gui.main_window import MainWindow

        with mock.patch("gui.main_window.AppUpdateCheckWorker.start"), \
             mock.patch("gui.views.spotify_view.SpotifyPKCEAuth.load_cached_token", return_value=None), \
             mock.patch("gui.views.spotify_view.SpotifyWorker"):
            self.window = MainWindow(dict(DEFAULT_CONFIG))
        self.addCleanup(self.window.deleteLater)
        self.queue = self.window.download_queue
        self.chip = self.window.title_bar.queue_chip

    def test_starts_empty(self):
        self.assertEqual(self.chip.label.text(), "Queue: 0")
        self.assertEqual(self.window.title_bar.spotify_chip.label.text(), "Spotify: Not connected")

    def test_counts_pending_items(self):
        for i in range(3):
            self.queue.add_track("Artist", f"Track {i}")
        self.assertEqual(self.chip.label.text(), "Queue: 3")

    def test_shows_downloading_and_remaining_then_updates_on_completion(self):
        from gui.workers.download_queue import DownloadStatus

        items = [self.queue.add_track("Artist", f"Track {i}") for i in range(3)]
        self.queue.update_item_status(items[0].id, DownloadStatus.DOWNLOADING, progress=0)
        self.assertIn("Downloading 1", self.chip.label.text())
        self.assertIn("2 queued", self.chip.label.text())
        self.queue.update_item_status(items[0].id, DownloadStatus.COMPLETED, progress=100)
        self.assertEqual(self.chip.label.text(), "Queue: 2")

    def test_clearing_queue_resets_chip(self):
        self.queue.add_track("Artist", "Track")
        self.queue.clear_all()
        self.assertEqual(self.chip.label.text(), "Queue: 0")


if __name__ == "__main__":
    unittest.main()
