"""Tests for failed-track recording, retry, resume and scheduled batches.
Downloads are mocked at run_download or batch_download, nothing runs yt-dlp.
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)
    sys.path.insert(0, os.path.dirname(THIS_DIR))

from downloader import base_downloader, retry_manager
from downloader.ytdlp_command import DownloadResult
from managers import resume_manager, schedule_manager

QUIET_CONFIG = {
    "auto_backup": False,
    "auto_cleanup": False,
    "auto_metadata_embedding": False,
    "enable_metadata_embedding": False,
    "sleep_between": 0,
    "output_dir": "unused",
    "audio_format": "mp3",
}


def _tracks(count):
    """Return count simple track dicts.

    @param count: Number of tracks.
    """
    return [{"artist": f"Artist {i}", "track": f"Song {i}", "duration_ms": 180000 + i} for i in range(count)]


class TempFilesMixin:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.failed_file = os.path.join(self.tmp.name, "failed_downloads.json")
        self.progress_file = os.path.join(self.tmp.name, "download_progress.json")
        for target, value in (
            ("downloader.retry_manager.FAILED_FILE", self.failed_file),
            ("managers.resume_manager.PROGRESS_FILE", self.progress_file),
        ):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def read(self, path):
        """Return the parsed JSON in path.

        @param path: File to read.
        """
        with open(path, encoding="utf-8") as f:
            return json.load(f)


class TestFailedTrackRecording(TempFilesMixin, unittest.TestCase):
    def test_add_failed_track_from_many_threads_loses_nothing(self):
        tracks = _tracks(40)
        barrier = threading.Barrier(8)

        def worker(chunk):
            barrier.wait()
            for t in chunk:
                retry_manager.add_failed_track(t["artist"], t["track"], error="boom")

        threads = [threading.Thread(target=worker, args=(tracks[i::8],)) for i in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        saved = self.read(self.failed_file)
        self.assertEqual(len(saved), 40)
        self.assertEqual({t["track"] for t in saved}, {t["track"] for t in tracks})

    def test_batch_download_records_failures_from_four_workers_and_returns_them(self):
        tracks = _tracks(24)
        lock = threading.Lock()
        active = {"now": 0, "max": 0}

        def fake_run(track, *args, **kwargs):
            with lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
            threading.Event().wait(0.01)
            with lock:
                active["now"] -= 1
            if int(track["track"].split()[-1]) % 2:
                return DownloadResult(False, None, "No YouTube results for this track.")
            return DownloadResult(True, os.path.join(self.tmp.name, "x.mp3"), None)

        with mock.patch("downloader.base_downloader.run_download", side_effect=fake_run):
            failed = asyncio.run(base_downloader.batch_download(tracks, self.tmp.name, "mp3", config=QUIET_CONFIG))

        expected = [t for t in tracks if int(t["track"].split()[-1]) % 2]
        self.assertEqual(failed, expected)
        saved = self.read(self.failed_file)
        self.assertEqual(sorted(t["track"] for t in saved), sorted(t["track"] for t in expected))
        self.assertTrue(all(t["last_error"] == "No YouTube results for this track." for t in saved))
        self.assertTrue(all(t["duration_ms"] for t in saved))
        self.assertGreater(active["max"], 1)

    def test_batch_download_sleeps_between_tracks_per_worker(self):
        config = dict(QUIET_CONFIG, sleep_between=3)
        with mock.patch("downloader.base_downloader.run_download", return_value=DownloadResult(True, "x.mp3", None)), \
             mock.patch("downloader.base_downloader.time.sleep") as sleep:
            asyncio.run(base_downloader.batch_download(_tracks(5), self.tmp.name, "mp3", config=config))
        self.assertEqual([c.args for c in sleep.call_args_list].count((3.0,)), 5)

    def test_download_track_returns_result_and_records_failure(self):
        with mock.patch("downloader.base_downloader.run_download", return_value=DownloadResult(False, None, "HTTP 429")), \
             mock.patch("downloader.base_downloader.time.sleep"):
            result = base_downloader.download_track("A", "B", self.tmp.name, "mp3", 0, config=QUIET_CONFIG)
        self.assertFalse(result.success)
        saved = self.read(self.failed_file)
        self.assertEqual([(t["artist"], t["track"], t["last_error"]) for t in saved], [("A", "B", "HTTP 429")])


class TestRetryFailed(TempFilesMixin, unittest.TestCase):
    def _write_failed(self, entries):
        """Write entries as the failed downloads file.

        @param entries: List of failed track dicts.
        """
        with open(self.failed_file, "w", encoding="utf-8") as f:
            json.dump(entries, f)

    def test_retry_that_fails_again_stays_in_list_with_new_error(self):
        self._write_failed([{"artist": "A", "track": "B", "duration_ms": 1000, "attempt_count": 1, "last_error": "old"}])
        config = dict(QUIET_CONFIG, retry_attempts=3, retry_delay=0)

        with mock.patch("downloader.retry_manager.download_track", return_value=DownloadResult(False, None, "new error")) as dl, \
             mock.patch("downloader.retry_manager.time.sleep"):
            retry_manager.retry_failed(config)

        saved = self.read(self.failed_file)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["last_error"], "new error")
        self.assertEqual(saved[0]["attempt_count"], 3)
        self.assertEqual(dl.call_count, 2)
        self.assertFalse(dl.call_args.kwargs["record_failure"])
        self.assertEqual(dl.call_args.kwargs["track_data"], {"artist": "A", "track": "B", "duration_ms": 1000})

    def test_retry_that_succeeds_is_removed(self):
        self._write_failed([
            {"artist": "A", "track": "B", "attempt_count": 1, "last_error": "old"},
            {"artist": "C", "track": "D", "attempt_count": 1, "last_error": "old"},
        ])
        config = dict(QUIET_CONFIG, retry_attempts=2, retry_delay=0)

        def fake(artist, *args, **kwargs):
            return DownloadResult(artist == "A", None, None if artist == "A" else "still bad")

        with mock.patch("downloader.retry_manager.download_track", side_effect=fake), \
             mock.patch("downloader.retry_manager.time.sleep"):
            retry_manager.retry_failed(config)

        saved = self.read(self.failed_file)
        self.assertEqual([(t["artist"], t["last_error"]) for t in saved], [("C", "still bad")])

    def test_retry_uses_saved_output_dir(self):
        self._write_failed([{"artist": "A", "track": "B", "attempt_count": 0, "output_dir": "playlist_dir"}])
        config = dict(QUIET_CONFIG, retry_attempts=1, retry_delay=0)
        with mock.patch("downloader.retry_manager.download_track", return_value=DownloadResult(True, "x", None)) as dl:
            retry_manager.retry_failed(config)
        self.assertEqual(dl.call_args.args[2], "playlist_dir")

    def test_retry_backup_receives_config(self):
        self._write_failed([{"artist": "A", "track": "B", "attempt_count": 0}])
        config = dict(QUIET_CONFIG, auto_backup=True, retry_attempts=1, retry_delay=0)
        with mock.patch("downloader.retry_manager.download_track", return_value=DownloadResult(True, "x", None)), \
             mock.patch("managers.backup_manager.backup_json_file") as backup:
            retry_manager.retry_failed(config)
        backup.assert_called_once_with(self.failed_file, config)

    def test_real_backup_json_file_accepts_config(self):
        import inspect
        from managers.backup_manager import backup_json_file

        inspect.signature(backup_json_file).bind(self.failed_file, QUIET_CONFIG)


class TestResume(TempFilesMixin, unittest.TestCase):
    def test_resume_writes_back_only_failed_tracks_and_passes_config(self):
        pending = _tracks(3)
        resume_manager.save_progress(pending)
        config = dict(QUIET_CONFIG)

        batch = mock.AsyncMock(return_value=[pending[1]])
        with mock.patch("downloader.base_downloader.batch_download", batch):
            resume_manager.resume_batch(config)

        self.assertEqual(self.read(self.progress_file), [pending[1]])
        self.assertIs(batch.call_args.kwargs["config"], config)

    def test_resume_clears_file_when_everything_succeeds(self):
        resume_manager.save_progress(_tracks(2))
        with mock.patch("downloader.base_downloader.batch_download", mock.AsyncMock(return_value=[])):
            resume_manager.resume_batch(dict(QUIET_CONFIG))
        self.assertEqual(self.read(self.progress_file), [])

    def test_batch_saves_progress_first_and_leaves_failures(self):
        tracks = _tracks(4)
        seen_during = []

        def fake_run(track, *args, **kwargs):
            seen_during.append(self.read(self.progress_file))
            ok = track["track"] != "Song 2"
            return DownloadResult(ok, "x.mp3" if ok else None, None if ok else "nope")

        with mock.patch("downloader.base_downloader.run_download", side_effect=fake_run):
            failed = asyncio.run(base_downloader.batch_download(
                tracks, self.tmp.name, "mp3", config=QUIET_CONFIG, save_progress_first=True,
            ))

        self.assertTrue(all(snapshot == tracks for snapshot in seen_during))
        self.assertEqual(failed, [tracks[2]])
        self.assertEqual(self.read(self.progress_file), [tracks[2]])


class _StopLoop(Exception):
    pass


class TestSchedule(unittest.TestCase):
    def test_scheduled_job_passes_config_to_batch_download(self):
        config = dict(QUIET_CONFIG)
        sched = mock.MagicMock()
        sched.run_pending.side_effect = _StopLoop()
        pending = _tracks(2)
        batch = mock.AsyncMock(return_value=[])

        with mock.patch("builtins.input", return_value="03:00"), \
             mock.patch.object(schedule_manager, "schedule", sched):
            schedule_manager.schedule_download(config)

        job = sched.every.return_value.day.at.return_value.do.call_args.args[0]
        with mock.patch.object(schedule_manager, "load_primary_tracks", return_value=pending), \
             mock.patch("utils.track_checker.check_downloaded_files", return_value=([], pending)), \
             mock.patch.object(schedule_manager, "batch_download", batch):
            job()

        self.assertIs(batch.call_args.kwargs["config"], config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
