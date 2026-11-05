"""Core-functionality tests for the download pipeline: the yt-dlp command that gets
built for a track, and DownloadWorker._download_single's success/failure handling.
These are the paths that must work before every release, so no real download or
network access happens here - subprocess.Popen is mocked.
"""
import io
import os
import tempfile
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in os.sys.path:
    os.sys.path.insert(0, THIS_DIR)
    os.sys.path.insert(0, os.path.dirname(THIS_DIR))

from downloader.base_downloader import _get_base_filename, _download_worker
from gui.workers.download_queue import DownloadQueue, QueueItem, DownloadStatus
from gui.workers.download_worker import DownloadWorker


def _fake_popen(returncode=0, stdout="", stderr=""):
    proc = mock.MagicMock()
    proc.stdout = io.StringIO(stdout + stderr)
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.wait.return_value = returncode
    return proc


class TestGetBaseFilename(unittest.TestCase):
    def test_joins_artist_and_track(self):
        self.assertEqual(_get_base_filename("Artist A", "Track One"), "Artist A - Track One")

    def test_slashes_are_sanitized_to_avoid_path_traversal(self):
        self.assertEqual(_get_base_filename("AC/DC", "T.N.T"), "AC-DC - T.N.T")


class TestBaseDownloaderCommand(unittest.TestCase):
    def test_download_worker_builds_expected_yt_dlp_command(self):
        with tempfile.TemporaryDirectory() as td:
            track = {"artist": "Artist A", "track": "Song One"}

            with mock.patch("subprocess.Popen", return_value=_fake_popen(returncode=0)) as popen, \
                 mock.patch("downloader.metadata.find_downloaded_audio_path", return_value=None), \
                 mock.patch("downloader.base_downloader._record_failure"):
                _download_worker(track, td, "mp3", config={})

            cmd = popen.call_args[0][0]
            self.assertEqual(cmd[0], "yt-dlp")
            self.assertIn("ytsearch1:Artist A - Song One", cmd)
            self.assertIn("-x", cmd)
            self.assertIn("--audio-format", cmd)
            self.assertIn("mp3", cmd)
            self.assertIn("-o", cmd)
            expected_output = os.path.join(td, "Artist A - Song One.%(ext)s")
            self.assertIn(expected_output, cmd)

    def test_extra_ytdlp_args_from_config_are_appended(self):
        with tempfile.TemporaryDirectory() as td:
            track = {"artist": "Artist A", "track": "Song One"}
            config = {"ytdlp_extra_args": "--limit-rate 1M"}

            with mock.patch("subprocess.Popen", return_value=_fake_popen(returncode=0)) as popen, \
                 mock.patch("downloader.metadata.find_downloaded_audio_path", return_value=None), \
                 mock.patch("downloader.base_downloader._record_failure"):
                _download_worker(track, td, "mp3", config=config)

            cmd = popen.call_args[0][0]
            self.assertIn("--limit-rate", cmd)
            self.assertIn("1M", cmd)

    def test_embeds_metadata_when_audio_file_is_found(self):
        with tempfile.TemporaryDirectory() as td:
            track = {"artist": "Artist A", "track": "Song One"}
            audio_path = os.path.join(td, "Artist A - Song One.mp3")

            with mock.patch("subprocess.Popen", return_value=_fake_popen(returncode=0)), \
                 mock.patch("downloader.metadata.find_downloaded_audio_path", return_value=audio_path), \
                 mock.patch("downloader.metadata.embed_track_metadata", return_value=True) as embed:
                _download_worker(track, td, "mp3", config={})

            embed.assert_called_once()
            called_path, called_track = embed.call_args[0][0], embed.call_args[0][1]
            self.assertEqual(called_path, audio_path)
            self.assertEqual(called_track, track)


class TestYoutubeLinkDownloader(unittest.TestCase):
    def _run(self, func, *args):
        """Run a link download with yt-dlp and the prompt mocked, and return the subprocess.run calls.

        @param func: download_from_link or download_from_playlist.
        @param args: Positional arguments for func.
        """
        from downloader import youtube_link_downloader as yld

        info = mock.MagicMock(returncode=0, stdout='{"title": "T", "playlist_title": "P"}\n')
        with mock.patch.object(yld.subprocess, "run", return_value=info) as run, \
             mock.patch.object(yld.questionary, "confirm") as confirm:
            confirm.return_value.ask.return_value = True
            func(*args, config={})
        return run.call_args_list

    def test_single_video_download_passes_no_playlist(self):
        from downloader.youtube_link_downloader import download_from_link

        calls = self._run(download_from_link, "https://youtu.be/x?list=PL1", "out", "mp3")
        self.assertIn("--no-playlist", calls[-1].args[0])

    def test_playlist_download_does_not_pass_no_playlist(self):
        from downloader.youtube_link_downloader import download_from_playlist

        calls = self._run(download_from_playlist, "https://youtube.com/playlist?list=PL1", "out", "mp3", 0)
        self.assertNotIn("--no-playlist", calls[-1].args[0])

    def test_captured_info_call_is_hidden_but_downloads_keep_the_console(self):
        from downloader.youtube_link_downloader import download_from_link, download_from_playlist

        for func, args in (
            (download_from_link, ("https://youtu.be/x", "out", "mp3")),
            (download_from_playlist, ("https://youtube.com/playlist?list=PL1", "out", "mp3", 0)),
        ):
            with mock.patch("downloader.youtube_link_downloader.hidden_subprocess_kwargs",
                            return_value={"creationflags": 0x08000000}):
                calls = self._run(func, *args)
            self.assertEqual(calls[0].kwargs.get("creationflags"), 0x08000000, func.__name__)
            self.assertNotIn("creationflags", calls[-1].kwargs, func.__name__)


class TestDownloadWorkerSingleTrack(unittest.TestCase):
    def _make_worker(self, tmp_dir, config_overrides=None):
        config = {"output_dir": tmp_dir, "audio_format": "mp3", "enable_metadata_embedding": False}
        config.update(config_overrides or {})
        queue = DownloadQueue()
        return DownloadWorker(queue, config)

    def test_success_finds_downloaded_file_at_expected_path(self):
        with tempfile.TemporaryDirectory() as td:
            worker = self._make_worker(td)
            item = QueueItem(id="1", artist="Artist A", track="Song One", status=DownloadStatus.PENDING)

            expected_path = os.path.join(td, "Artist A - Song One.mp3")

            def fake_popen(*args, **kwargs):
                # Simulate yt-dlp having written the output file before returning.
                with open(expected_path, "w") as f:
                    f.write("fake audio")
                return _fake_popen(returncode=0)

            with mock.patch("subprocess.Popen", side_effect=fake_popen):
                success, file_path, error = worker._download_single(item)

            self.assertTrue(success)
            self.assertEqual(file_path, expected_path)
            self.assertIsNone(error)

    def test_success_falls_back_to_scanning_other_extensions(self):
        with tempfile.TemporaryDirectory() as td:
            worker = self._make_worker(td)
            item = QueueItem(id="1", artist="Artist A", track="Song One", status=DownloadStatus.PENDING)

            # yt-dlp requested mp3 but actually produced m4a (e.g. no ffmpeg conversion available).
            actual_path = os.path.join(td, "Artist A - Song One.m4a")

            def fake_popen(*args, **kwargs):
                with open(actual_path, "w") as f:
                    f.write("fake audio")
                return _fake_popen(returncode=0)

            with mock.patch("subprocess.Popen", side_effect=fake_popen):
                success, file_path, error = worker._download_single(item)

            self.assertTrue(success)
            self.assertEqual(file_path, actual_path)

    def test_nonzero_returncode_reports_stderr_as_error(self):
        with tempfile.TemporaryDirectory() as td:
            worker = self._make_worker(td)
            item = QueueItem(id="1", artist="Artist A", track="Song One", status=DownloadStatus.PENDING)

            with mock.patch("subprocess.Popen", return_value=_fake_popen(returncode=1, stderr="ERROR: video unavailable")):
                success, file_path, error = worker._download_single(item)

            self.assertFalse(success)
            self.assertIsNone(file_path)
            self.assertEqual(error, "ERROR: video unavailable")

    def test_missing_yt_dlp_binary_reports_clear_error(self):
        with tempfile.TemporaryDirectory() as td:
            worker = self._make_worker(td)
            item = QueueItem(id="1", artist="Artist A", track="Song One", status=DownloadStatus.PENDING)

            with mock.patch("subprocess.Popen", side_effect=FileNotFoundError()):
                success, file_path, error = worker._download_single(item)

            self.assertFalse(success)
            self.assertIsNone(file_path)
            self.assertIn("yt-dlp not found", error)

    def test_relative_output_dir_is_made_absolute_and_created(self):
        with tempfile.TemporaryDirectory() as td:
            queue = DownloadQueue()
            config = {"output_dir": "relative_music_dir", "audio_format": "mp3", "enable_metadata_embedding": False}
            worker = DownloadWorker(queue, config)
            item = QueueItem(id="1", artist="Artist A", track="Song One", status=DownloadStatus.PENDING)

            fake_base_dir = td

            with mock.patch("subprocess.Popen", return_value=_fake_popen(returncode=0)), \
                 mock.patch("os.path.dirname", return_value=fake_base_dir):
                worker._download_single(item)

            # The absolute output dir should have been created under the (mocked) base dir.
            self.assertTrue(os.path.isdir(os.path.join(fake_base_dir, "relative_music_dir")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
