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

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from config import DEFAULT_CONFIG


def _fake_ytdlp_file(test_case: unittest.TestCase) -> str:
    """Create an empty file that stands in for a configured yt-dlp binary.

    @param test_case: Test that owns the temporary directory cleanup.
    """
    td = tempfile.TemporaryDirectory()
    test_case.addCleanup(td.cleanup)
    path = os.path.join(td.name, "yt-dlp.exe")
    with open(path, "w") as f:
        f.write("")
    return path


class _NoBlockingCalls:
    """Patches subprocess and urlopen so any synchronous call is recorded."""

    def __enter__(self):
        """Start the patches and return self."""
        self.patches = [
            mock.patch("subprocess.run"),
            mock.patch("subprocess.Popen"),
            mock.patch("subprocess.check_output"),
            mock.patch("urllib.request.urlopen"),
        ]
        self.mocks = [p.start() for p in self.patches]
        return self

    def __exit__(self, *exc):
        """Stop the patches."""
        for p in self.patches:
            p.stop()
        return False

    def calls(self) -> list:
        """Return every recorded call across the patched functions."""
        return [c for m in self.mocks for c in m.call_args_list]


class TestSettingsViewConstruction(unittest.TestCase):
    def test_construction_does_not_run_ytdlp(self):
        from gui.views.settings_view import SettingsView

        config = dict(DEFAULT_CONFIG, ytdlp_path=_fake_ytdlp_file(self))
        with _NoBlockingCalls() as guard:
            view = SettingsView(config)

        self.assertEqual(guard.calls(), [])
        view.deleteLater()

    def test_status_result_updates_labels(self):
        from gui.views.settings_view import SettingsView

        with _NoBlockingCalls():
            view = SettingsView(dict(DEFAULT_CONFIG))
        view._apply_ytdlp_status("C:/bin/yt-dlp.exe", "2024.08.06")
        self.assertIn("2024.08.06", view.ytdlp_status_label.text())
        self.assertEqual(view.ytdlp_update_btn.text(), "Check for Updates")

        view._apply_ytdlp_status("", "")
        self.assertEqual(view.ytdlp_status_label.text(), "Not installed")
        self.assertEqual(view.ytdlp_update_btn.text(), "Install yt-dlp")
        view.deleteLater()

    def test_check_status_runs_in_worker(self):
        from gui.views.settings_view import SettingsView

        with _NoBlockingCalls():
            view = SettingsView(dict(DEFAULT_CONFIG))
        with mock.patch("gui.views.settings_view.YtdlpStatusWorker") as worker_cls:
            worker_cls.return_value.isRunning.return_value = False
            view._check_ytdlp_status()
        worker_cls.return_value.start.assert_called_once()
        view.deleteLater()


class TestYtdlpWorkers(unittest.TestCase):
    def test_update_worker_emits_only_when_update_available(self):
        from gui.workers.ytdlp_update_worker import YtdlpUpdateCheckWorker

        worker = YtdlpUpdateCheckWorker("C:/bin/yt-dlp.exe")
        received = []
        worker.update_available.connect(received.append)
        info = {"update_available": True, "current_version": "1", "latest_version": "2"}
        with mock.patch(
            "gui.workers.ytdlp_update_worker.check_ytdlp_updates", return_value=info
        ) as check:
            worker.run()
        check.assert_called_once_with("C:/bin/yt-dlp.exe")
        self.assertEqual(received, [info])

        with mock.patch(
            "gui.workers.ytdlp_update_worker.check_ytdlp_updates",
            return_value={"update_available": False},
        ):
            worker.run()
        self.assertEqual(len(received), 1)

    def test_status_worker_emits_path_and_version(self):
        from gui.workers.ytdlp_update_worker import YtdlpStatusWorker

        worker = YtdlpStatusWorker(None)
        received = []
        worker.status_ready.connect(lambda p, v: received.append((p, v)))
        with mock.patch(
            "gui.workers.ytdlp_update_worker.find_ytdlp", return_value=(None, None)
        ):
            worker.run()
        self.assertEqual(received, [("", "")])

    def test_find_ytdlp_prefers_configured_binary(self):
        from tools import ytdlp_update_checker

        path = _fake_ytdlp_file(self)
        with mock.patch.object(
            ytdlp_update_checker, "get_installed_version", return_value="2024.08.06"
        ) as get_version:
            self.assertEqual(ytdlp_update_checker.find_ytdlp(path), (path, "2024.08.06"))
        get_version.assert_called_once_with(path)

        with mock.patch("tools.ytdlp_update_checker.shutil.which", return_value=None):
            self.assertEqual(ytdlp_update_checker.find_ytdlp(None), (None, None))


class TestMainWindowStartup(unittest.TestCase):
    def _make_window(self, config: dict):
        """Construct MainWindow with update threads and Spotify token lookups stubbed.

        @param config: Config dict for the window.
        """
        from gui.main_window import MainWindow

        with mock.patch("gui.main_window.AppUpdateCheckWorker.start"), mock.patch(
            "gui.views.spotify_view.SpotifyPKCEAuth.load_cached_token", return_value=None
        ):
            window = MainWindow(config)
        self.addCleanup(window.deleteLater)
        return window

    def test_construction_makes_no_blocking_calls(self):
        config = dict(DEFAULT_CONFIG, ytdlp_path=_fake_ytdlp_file(self))
        with _NoBlockingCalls() as guard:
            self._make_window(config)
        self.assertEqual(guard.calls(), [])

    def test_start_ytdlp_update_check_uses_worker(self):
        with _NoBlockingCalls():
            window = self._make_window(dict(DEFAULT_CONFIG, ytdlp_path="C:/bin/yt-dlp.exe"))
        with mock.patch("gui.main_window.YtdlpUpdateCheckWorker") as worker_cls:
            window.start_ytdlp_update_check()
        worker_cls.assert_called_once_with("C:/bin/yt-dlp.exe", window)
        worker_cls.return_value.start.assert_called_once()

    def test_ytdlp_update_shows_banner_with_install_choice(self):
        with _NoBlockingCalls():
            window = self._make_window(dict(DEFAULT_CONFIG))
        window._on_ytdlp_update_available(
            {"update_available": True, "current_version": "2024.07.01", "latest_version": "2024.08.06"}
        )
        self.assertFalse(window.update_banner.isHidden())
        self.assertFalse(window.ytdlp_install_btn.isHidden())
        self.assertTrue(window.app_download_btn.isHidden())
        self.assertIn("2024.08.06", window.update_banner_label.text())

        with mock.patch.object(window.settings_view, "_check_ytdlp_updates") as install:
            window.ytdlp_install_btn.click()
        install.assert_called_once_with()
        self.assertIs(window.view_stack.currentWidget(), window.settings_view)

    def test_app_and_ytdlp_updates_share_banner(self):
        with _NoBlockingCalls():
            window = self._make_window(dict(DEFAULT_CONFIG))
        window._on_app_update_available(
            {"latest_version": "v9.9.9", "current_version": "1.0.0", "release_url": "https://x"}
        )
        window._on_ytdlp_update_available(
            {"update_available": True, "current_version": "2024.07.01", "latest_version": "2024.08.06"}
        )
        text = window.update_banner_label.text()
        self.assertIn("v9.9.9", text)
        self.assertIn("2024.08.06", text)
        self.assertFalse(window.app_download_btn.isHidden())
        self.assertFalse(window.ytdlp_install_btn.isHidden())

    def test_spotify_view_navigation_signal_switches_view(self):
        with _NoBlockingCalls():
            window = self._make_window(dict(DEFAULT_CONFIG))
        window._navigate_to_view("spotify")
        window.spotify_view.navigate_to.emit("settings")
        self.assertIs(window.view_stack.currentWidget(), window.settings_view)

    def test_spotify_open_settings_navigates_once(self):
        with _NoBlockingCalls():
            window = self._make_window(dict(DEFAULT_CONFIG))
        with mock.patch.object(window.sidebar, "setCurrentRow") as set_row:
            window.spotify_view._open_settings()
        set_row.assert_called_once_with(4)


class TestSettingsReset(unittest.TestCase):
    def test_reset_keeps_spotify_settings(self):
        from gui.views import settings_view as settings_module

        config = dict(DEFAULT_CONFIG, spotify_client_id="my-app-id", audio_format="flac")
        with _NoBlockingCalls():
            view = settings_module.SettingsView(config)
        self.addCleanup(view.deleteLater)
        with mock.patch.object(
            settings_module.QMessageBox, "question", return_value=settings_module.QMessageBox.Yes
        ), mock.patch.object(settings_module.QMessageBox, "information"):
            view._reset_to_defaults()
        self.assertEqual(view.config["spotify_client_id"], "my-app-id")
        self.assertEqual(view.client_id_input.text(), "my-app-id")
        self.assertEqual(view.config["audio_format"], DEFAULT_CONFIG["audio_format"])


class TestGuiMainStartup(unittest.TestCase):
    def test_ytdlp_check_starts_after_show_without_prelaunch_dialog(self):
        import gui_main
        import gui.main_window

        order = mock.Mock()
        fake_window = order.window
        fake_qapp = mock.Mock()
        fake_qapp.return_value.exec.return_value = 0
        update_info = {"update_available": True, "current_version": "1", "latest_version": "2"}

        with mock.patch("PySide6.QtWidgets.QApplication", fake_qapp), mock.patch(
            "PySide6.QtWidgets.QMessageBox"
        ) as message_box, mock.patch.object(
            gui_main, "create_default_config"
        ), mock.patch.object(gui_main, "configure_bundled_binaries"), mock.patch.object(
            gui_main, "check_ffmpeg"
        ), mock.patch("config.load_config", return_value=dict(DEFAULT_CONFIG)), mock.patch(
            "tools.ytdlp_update_checker.check_ytdlp_updates", side_effect=order.check
        ), mock.patch.object(
            gui.main_window, "MainWindow", return_value=fake_window
        ), mock.patch("gui.resources.icons.get_app_icon"):
            order.check.return_value = update_info
            with self.assertRaises(SystemExit):
                gui_main.main()

        message_box.information.assert_not_called()
        order.check.assert_not_called()
        names = [c[0] for c in order.mock_calls]
        self.assertIn("window.show", names)
        self.assertIn("window.start_ytdlp_update_check", names)
        self.assertLess(names.index("window.show"), names.index("window.start_ytdlp_update_check"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
