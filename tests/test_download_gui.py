"""Tests for the GUI download queue, worker and downloads view.

run_download, ffmpeg discovery and message boxes are mocked, so no yt-dlp process,
network access or modal dialog is involved.
"""
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)
    sys.path.insert(0, os.path.dirname(THIS_DIR))

from PySide6.QtWidgets import QApplication, QMessageBox

from downloader.ytdlp_command import DownloadResult
from gui.views.downloads_view import DownloadsView
from gui.workers.download_queue import DownloadQueue, DownloadStatus
from gui.workers.download_worker import DownloadWorker

APP = QApplication.instance() or QApplication([])

RUN_DOWNLOAD = "gui.workers.download_worker.run_download"
CONFIGURE_FFMPEG = "utils.ffmpeg.configure_ffmpeg_path"
VIEW_MESSAGEBOX = "gui.views.downloads_view.QMessageBox"

SOURCE_TRACK = {
    "artist": "Artist A",
    "track": "Song One",
    "album": "Album X",
    "duration_ms": 201000,
    "album_art_url": "https://example.com/art.jpg",
    "uri": "spotify:track:abc",
}


def _wait_until(condition, timeout=5.0):
    """Process Qt events until condition() is true or the timeout passes.

    @param condition: Callable returning True when the wait is over.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    APP.processEvents()
    return condition()


SUCCESS = DownloadResult(True, "C:/music/song.mp3", None)


def _blocking_run(proc, release):
    """Return a run_download fake that hands proc to popen_hook and runs until cancelled and released.

    @param proc: Fake process passed to popen_hook.
    @param release: Event that lets the fake return once cancellation was seen.
    """
    def fake(track, output_dir, audio_format, config, *, popen_hook=None, cancel_check=None, output_hook=None):
        if popen_hook:
            popen_hook(proc)
        deadline = time.monotonic() + 5
        while not cancel_check() and time.monotonic() < deadline:
            time.sleep(0.01)
        release.wait(5)
        return DownloadResult(False, None, "Cancelled")
    return fake


def _fake_process():
    """Return a mock Popen that looks like it is still running."""
    proc = mock.MagicMock()
    proc.poll.return_value = None
    return proc


class TestDownloadQueue(unittest.TestCase):
    def test_add_tracks_keeps_full_track_dict(self):
        [item] = DownloadQueue().add_tracks([SOURCE_TRACK], playlist="Mix")
        self.assertEqual(item.track_data, SOURCE_TRACK)

    def test_add_item_keeps_album(self):
        queue = DownloadQueue()
        item = queue.add_item("Artist A", "Song One", album="Album X")
        self.assertEqual(item.track_data.get("album"), "Album X")

    def test_add_tracks_emits_queue_updated_once_per_batch(self):
        queue = DownloadQueue()
        updates = []
        queue.queue_updated.connect(updates.append)
        tracks = [{"artist": f"Artist {i}", "track": f"Song {i}"} for i in range(2000)]
        items = queue.add_tracks(tracks)
        self.assertEqual(len(items), 2000)
        self.assertLessEqual(len(updates), 2)
        self.assertEqual(updates[-1], 2000)

    def test_cancelled_items_are_retryable(self):
        queue = DownloadQueue()
        cancelled = queue.add_track("Artist A", "Song One")
        failed = queue.add_track("Artist B", "Song Two")
        queue.update_item_status(cancelled.id, DownloadStatus.CANCELLED, error_message="Cancelled by user")
        queue.update_item_status(failed.id, DownloadStatus.FAILED, error_message="boom")
        self.assertFalse(queue.has_pending())

        queue.retry_failed()

        self.assertEqual(cancelled.status, DownloadStatus.PENDING)
        self.assertIsNone(cancelled.error_message)
        self.assertEqual(failed.status, DownloadStatus.PENDING)
        self.assertTrue(queue.has_pending())
        self.assertEqual(queue.pending_count, 2)


class TestDownloadWorker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {"output_dir": self.tmp.name, "audio_format": "mp3", "enable_metadata_embedding": False}
        patcher = mock.patch(CONFIGURE_FFMPEG, return_value="ffmpeg")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_cancel_during_download_terminates_yt_dlp_and_marks_cancelled(self):
        queue = DownloadQueue()
        item = queue.add_track("Artist A", "Song One")
        worker = DownloadWorker(queue, self.config)
        proc = _fake_process()
        release = threading.Event()
        release.set()
        with mock.patch(RUN_DOWNLOAD, side_effect=_blocking_run(proc, release)):
            worker.start()
            self.assertTrue(_wait_until(lambda: worker._process is not None))
            worker.cancel()
            self.assertTrue(worker.wait(5000))
        proc.terminate.assert_called()
        self.assertEqual(item.status, DownloadStatus.CANCELLED)

    def test_track_finished_before_cancel_stays_completed(self):
        queue = DownloadQueue()
        item = queue.add_track("Artist A", "Song One")
        worker = DownloadWorker(queue, self.config)

        def finish_then_cancel(*args, **kwargs):
            worker._cancelled = True
            return SUCCESS

        with mock.patch(RUN_DOWNLOAD, side_effect=finish_then_cancel):
            worker.run()
        self.assertEqual(item.status, DownloadStatus.COMPLETED)
        self.assertEqual(item.file_path, SUCCESS.path)

    def test_full_track_data_reaches_run_download_and_metadata(self):
        queue = DownloadQueue()
        queue.add_tracks([SOURCE_TRACK])
        config = dict(self.config, enable_metadata_embedding=True)
        worker = DownloadWorker(queue, config)
        audio_path = os.path.join(self.tmp.name, "Artist A - Song One.mp3")

        with mock.patch(RUN_DOWNLOAD, return_value=DownloadResult(True, audio_path, None)) as run, \
             mock.patch("downloader.metadata.embed_track_metadata", return_value=True) as embed:
            worker.run()

        self.assertEqual(run.call_args[0][0], SOURCE_TRACK)
        self.assertEqual(run.call_args[0][3], config)
        embed.assert_called_once()
        self.assertEqual(embed.call_args[0][0], audio_path)
        self.assertEqual(embed.call_args[0][1], SOURCE_TRACK)
        self.assertIs(embed.call_args.kwargs["config"], config)

    def test_real_embed_track_metadata_accepts_the_worker_call(self):
        import inspect
        from downloader.metadata import embed_track_metadata

        inspect.signature(embed_track_metadata).bind(
            "x.mp3", {}, template="basic", allow_musicbrainz=True, config=self.config,
        )

    def test_metadata_failure_is_logged(self):
        queue = DownloadQueue()
        queue.add_track("Artist A", "Song One")
        worker = DownloadWorker(queue, dict(self.config, enable_metadata_embedding=True))

        with mock.patch(RUN_DOWNLOAD, return_value=SUCCESS), \
             mock.patch("downloader.metadata.embed_track_metadata", side_effect=RuntimeError("tag write failed")), \
             mock.patch("gui.workers.download_worker.log_error") as log_error:
            worker.run()

        log_error.assert_called_once()
        self.assertIn("tag write failed", log_error.call_args[0][0])

    def test_ffmpeg_missing_emits_all_completed(self):
        queue = DownloadQueue()
        item = queue.add_track("Artist A", "Song One")
        worker = DownloadWorker(queue, self.config)
        received = []
        worker.all_completed.connect(lambda s, f: received.append((s, f)))

        with mock.patch(CONFIGURE_FFMPEG, side_effect=FileNotFoundError("FFmpeg not found")):
            worker.run()

        self.assertEqual(received, [(0, 1)])
        self.assertEqual(item.status, DownloadStatus.FAILED)


class TestDownloadsView(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {"output_dir": self.tmp.name, "audio_format": "mp3", "enable_metadata_embedding": False}
        self.queue = DownloadQueue()
        self.view = DownloadsView(self.config, self.queue)
        self.addCleanup(self.view.deleteLater)

        ffmpeg = mock.patch(CONFIGURE_FFMPEG, return_value="ffmpeg")
        self.configure_ffmpeg = ffmpeg.start()
        self.addCleanup(ffmpeg.stop)

        box = mock.patch(VIEW_MESSAGEBOX)
        self.messagebox = box.start()
        self.addCleanup(box.stop)
        self.messagebox.Yes = QMessageBox.Yes
        self.messagebox.No = QMessageBox.No
        self.messagebox.question.return_value = QMessageBox.Yes

    def _finish_worker(self):
        """Wait until the view has handled its worker's finished signal."""
        self.assertTrue(_wait_until(lambda: self.view.worker is None))

    def test_start_stays_disabled_until_worker_finished(self):
        self.queue.add_track("Artist A", "Song One")
        proc = _fake_process()
        release = threading.Event()

        with mock.patch(RUN_DOWNLOAD, side_effect=_blocking_run(proc, release)), \
             mock.patch("gui.views.downloads_view.DownloadWorker", side_effect=DownloadWorker) as ctor:
            self.view._start_downloads()
            worker = self.view.worker
            self.assertTrue(_wait_until(lambda: worker._process is not None))

            self.view._cancel_downloads()
            proc.terminate.assert_called()
            self.assertFalse(self.view.start_btn.isEnabled())

            self.queue.add_track("Artist B", "Song Two")
            self.view._start_downloads()
            self.assertIs(self.view.worker, worker)
            self.assertEqual(ctor.call_count, 1)
            self.assertIs(worker.parent(), self.view)

            release.set()
            self._finish_worker()

        self.assertTrue(self.view.start_btn.isEnabled())
        self.assertFalse(self.view.cancel_btn.isEnabled())

    def test_worker_finished_is_handled_on_the_gui_thread(self):
        from PySide6.QtCore import QThread

        threads = []
        original = DownloadsView._on_worker_finished

        def record(view, worker):
            threads.append(QThread.currentThread())
            original(view, worker)

        self.queue.add_track("Artist A", "Song One")
        with mock.patch(RUN_DOWNLOAD, return_value=SUCCESS), \
             mock.patch.object(DownloadsView, "_on_worker_finished", record):
            self.view._start_downloads()
            self._finish_worker()

        self.assertEqual(threads, [APP.thread()])

    def test_one_completion_message_with_counts_for_this_run(self):
        self.queue.add_track("Artist A", "Song One")
        with mock.patch(RUN_DOWNLOAD, return_value=SUCCESS), \
             mock.patch("gui.views.downloads_view.notify") as notice:
            self.view._start_downloads()
            self._finish_worker()
            self.assertEqual(notice.call_count, 1)

            self.queue.add_track("Artist B", "Song Two")
            self.view._start_downloads()
            self._finish_worker()

        self.assertEqual(notice.call_count, 2)
        self.assertIn("Downloaded 1 tracks", notice.call_args[0][0])

    def test_ffmpeg_missing_reenables_start(self):
        self.queue.add_track("Artist A", "Song One")
        self.configure_ffmpeg.side_effect = FileNotFoundError("FFmpeg not found")
        with mock.patch(RUN_DOWNLOAD) as run:
            self.view._start_downloads()
            self._finish_worker()
        run.assert_not_called()
        self.assertTrue(self.view.start_btn.isEnabled())
        self.assertFalse(self.view.pause_btn.isEnabled())
        self.assertFalse(self.view.cancel_btn.isEnabled())

    def test_failed_item_error_is_status_tooltip(self):
        self.queue.add_track("Artist A", "Song One")
        failure = DownloadResult(False, None, "No YouTube results for this track.")
        with mock.patch(RUN_DOWNLOAD, return_value=failure):
            self.view._start_downloads()
            self._finish_worker()
        self.assertEqual(self.view.table.item(0, 3).toolTip(), "No YouTube results for this track.")

        self.queue.retry_failed()
        self.assertEqual(self.view.table.item(0, 3).toolTip(), "")

    def test_batched_add_fills_table_and_stats(self):
        tracks = [{"artist": f"Artist {i}", "track": f"Song {i}"} for i in range(5)]
        self.queue.add_tracks(tracks, playlist="Mix")
        self.queue.add_track("Solo", "Single")
        self.assertEqual(self.view.table.rowCount(), 6)
        self.assertEqual(self.view.table.item(0, 1).text(), "Song 0")
        self.assertEqual(self.view.table.item(0, 2).text(), "Mix")
        self.assertEqual(self.view.table.item(5, 0).text(), "Solo")
        self.assertEqual(self.view.pending_card.value_label.text(), "6")

    def test_clear_all_while_running_waits_with_timeout(self):
        self.queue.add_track("Artist A", "Song One")
        proc = _fake_process()
        release = threading.Event()
        release.set()
        with mock.patch(RUN_DOWNLOAD, side_effect=_blocking_run(proc, release)):
            self.view._start_downloads()
            worker = self.view.worker
            self.assertTrue(_wait_until(lambda: worker._process is not None))
            with mock.patch.object(worker, "wait", wraps=worker.wait) as wait:
                self.view._clear_all()
            self._finish_worker()

        proc.terminate.assert_called()
        wait.assert_called_once()
        self.assertTrue(wait.call_args.args, "Clear All must wait with a timeout")
        self.assertEqual(self.queue.items, [])
        self.assertEqual(self.view.table.rowCount(), 0)
        self.assertTrue(self.view.start_btn.isEnabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
