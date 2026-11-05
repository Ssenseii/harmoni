"""Tests for the yt-dlp search command builder and the single-track run function.
subprocess.Popen is mocked, nothing touches the network or a real yt-dlp.
"""
import io
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

from downloader import ytdlp_command
from downloader.ytdlp_command import DownloadResult, build_search_command, run_download
from utils import ytdlp_args

NO_FFMPEG = mock.patch("downloader.ytdlp_command._ffmpeg_location", return_value=None)


def _fake_proc(returncode=0, output=""):
    """Return a mock Popen whose stdout yields output and which exits with returncode.

    @param returncode: Exit code reported by poll and wait.
    @param output: Text the fake yt-dlp prints.
    """
    proc = mock.MagicMock()
    proc.stdout = io.StringIO(output)
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.wait.return_value = returncode
    return proc


def _flag_value(cmd, flag):
    """Return the argument after flag in cmd.

    @param cmd: argv list.
    @param flag: Flag whose value is wanted.
    """
    return cmd[cmd.index(flag) + 1]


class TestBuildSearchCommand(unittest.TestCase):
    def test_without_duration_keeps_single_result_search_and_no_filter(self):
        with NO_FFMPEG:
            cmd = build_search_command({"artist": "Artist A", "track": "Song One"}, "out", "mp3", {})
        self.assertEqual(cmd[0], "yt-dlp")
        self.assertIn("ytsearch1:Artist A - Song One", cmd)
        self.assertNotIn("--match-filter", cmd)
        self.assertIn("--no-playlist", cmd)
        self.assertEqual(_flag_value(cmd, "--audio-format"), "mp3")
        self.assertIn("-x", cmd)
        self.assertEqual(_flag_value(cmd, "-o"), os.path.join("out", "Artist A - Song One.%(ext)s"))

    def test_with_duration_searches_five_and_filters_with_default_tolerance(self):
        track = {"artist": "Artist A", "track": "Song One", "duration_ms": 200000}
        with NO_FFMPEG:
            cmd = build_search_command(track, "out", "mp3", {})
        self.assertIn("ytsearch5:Artist A - Song One", cmd)
        self.assertEqual(_flag_value(cmd, "--match-filter"), "duration > 185 & duration < 215")
        self.assertEqual(_flag_value(cmd, "--max-downloads"), "1")
        self.assertIn("--no-playlist", cmd)

    def test_duration_as_csv_string_is_parsed(self):
        track = {"artist": "A", "track": "B", "duration_ms": "180500"}
        with NO_FFMPEG:
            cmd = build_search_command(track, "out", "mp3", {})
        self.assertEqual(_flag_value(cmd, "--match-filter"), "duration > 165 & duration < 196")

    def test_empty_or_bad_duration_falls_back_to_single_search(self):
        for value in ("", "abc", 0, None):
            with NO_FFMPEG:
                cmd = build_search_command({"artist": "A", "track": "B", "duration_ms": value}, "out", "mp3", {})
            self.assertIn("ytsearch1:A - B", cmd, value)
            self.assertNotIn("--match-filter", cmd)

    def test_tolerance_comes_from_config(self):
        track = {"artist": "A", "track": "B", "duration_ms": 100000}
        with NO_FFMPEG:
            cmd = build_search_command(track, "out", "mp3", {"match_duration_tolerance": 5})
        self.assertEqual(_flag_value(cmd, "--match-filter"), "duration > 95 & duration < 105")

    def test_ffmpeg_location_added_when_found(self):
        with mock.patch("utils.ffmpeg.get_ffmpeg_path", return_value=r"C:\ff\ffmpeg.exe"):
            cmd = build_search_command({"artist": "A", "track": "B"}, "out", "mp3", {})
        self.assertEqual(_flag_value(cmd, "--ffmpeg-location"), r"C:\ff\ffmpeg.exe")

    def test_ffmpeg_location_omitted_when_missing(self):
        with mock.patch("utils.ffmpeg.get_ffmpeg_path", side_effect=FileNotFoundError("nope")):
            cmd = build_search_command({"artist": "A", "track": "B"}, "out", "mp3", {})
        self.assertNotIn("--ffmpeg-location", cmd)

    def test_ytdlp_path_and_extra_args_from_config(self):
        config = {"ytdlp_path": r"C:\tools\yt-dlp.exe", "ytdlp_extra_args": "--limit-rate 1M"}
        with NO_FFMPEG:
            cmd = build_search_command({"artist": "A", "track": "B"}, "out", "mp3", config)
        self.assertEqual(cmd[0], r"C:\tools\yt-dlp.exe")
        self.assertEqual(cmd[-2:], ["--limit-rate", "1M"])

    def test_slashes_in_names_are_sanitised(self):
        self.assertEqual(ytdlp_command.get_base_filename("A\\B", "C/D"), "A-B - C-D")


class TestRunDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = self.tmp.name
        self.track = {"artist": "Artist A", "track": "Song One", "duration_ms": 200000}
        NO_FFMPEG.start()
        self.addCleanup(NO_FFMPEG.stop)

    def _write_audio(self, ext="mp3"):
        """Create the file yt-dlp would have written.

        @param ext: File extension.
        """
        path = os.path.join(self.out, f"Artist A - Song One.{ext}")
        with open(path, "w") as f:
            f.write("audio")
        return path

    def test_success_returns_found_path_and_hides_console(self):
        def fake_popen(*args, **kwargs):
            self.kwargs = kwargs
            self._write_audio()
            return _fake_proc(0, "[download] 100%\n")

        with mock.patch("subprocess.Popen", side_effect=fake_popen):
            result = run_download(self.track, self.out, "mp3", {})

        self.assertEqual(result, DownloadResult(True, os.path.join(self.out, "Artist A - Song One.mp3"), None))
        self.assertEqual(self.kwargs.get("stderr"), ytdlp_command.subprocess.STDOUT)
        if sys.platform == "win32":
            self.assertIn("creationflags", self.kwargs)

    def test_exit_101_max_downloads_counts_as_success(self):
        def fake_popen(*args, **kwargs):
            self._write_audio("m4a")
            return _fake_proc(101, "Maximum number of downloads reached, stopping due to --max-downloads\n")

        with mock.patch("subprocess.Popen", side_effect=fake_popen):
            result = run_download(self.track, self.out, "mp3", {})

        self.assertTrue(result.success)
        self.assertTrue(result.path.endswith(".m4a"))

    def test_exit_zero_without_file_is_a_failure(self):
        with mock.patch("subprocess.Popen", return_value=_fake_proc(0, "")):
            result = run_download(self.track, self.out, "mp3", {})
        self.assertFalse(result.success)
        self.assertIsNone(result.path)
        self.assertTrue(result.error)

    def test_exit_zero_with_every_result_filtered_reports_duration_mismatch(self):
        output = "[download] Some Video does not pass filter (duration > 185 & duration < 215), skipping ..\n" * 5
        with mock.patch("subprocess.Popen", return_value=_fake_proc(0, output)):
            result = run_download(self.track, self.out, "mp3", {})
        self.assertFalse(result.success)
        self.assertIn("track length", result.error)

    def test_empty_search_explains_sign_in(self):
        output = "[youtube:search] Extracting URL: ytsearch5:Artist A - Song One\n"
        with mock.patch("subprocess.Popen", return_value=_fake_proc(0, output)):
            result = run_download(self.track, self.out, "mp3", {})
        self.assertEqual(result.error, ytdlp_command.NO_RESULTS_MESSAGE)
        self.assertIn("--cookies-from-browser", result.error)

    def test_found_video_without_file_keeps_generic_error(self):
        output = "[youtube] abcdefghijk: Downloading webpage\n"
        with mock.patch("subprocess.Popen", return_value=_fake_proc(0, output)):
            result = run_download(self.track, self.out, "mp3", {})
        self.assertIn("no audio file was found", result.error)

    def test_stderr_is_mapped_to_short_errors(self):
        cases = {
            "ERROR: [youtube] abc: HTTP Error 429: Too Many Requests": "429",
            "ERROR: [youtube] abc: Sign in to confirm you're not a bot": "not a bot",
            "ERROR: [youtube] abc: Sign in to confirm your age.": "age-restricted",
            "ERROR: Postprocessing: ffprobe and ffmpeg not found. Please install": "FFmpeg not found",
            "ERROR: something unusual happened": "ERROR: something unusual happened",
        }
        for line, expected in cases.items():
            with mock.patch("subprocess.Popen", return_value=_fake_proc(1, f"[info] x\n{line}\n")):
                result = run_download(self.track, self.out, "mp3", {})
            self.assertFalse(result.success)
            self.assertIn(expected.lower(), result.error.lower(), line)

    def test_missing_binary_reports_clear_error(self):
        with mock.patch("subprocess.Popen", side_effect=FileNotFoundError()):
            result = run_download(self.track, self.out, "mp3", {})
        self.assertFalse(result.success)
        self.assertIn("yt-dlp not found", result.error)

    def test_cancel_check_terminates_process(self):
        proc = _fake_proc(None, "")
        stopped = threading.Event()

        def terminate():
            stopped.set()
            proc.poll.return_value = -15
            proc.returncode = -15

        proc.terminate.side_effect = terminate
        proc.wait.side_effect = lambda timeout=None: -15
        hooked = []

        with mock.patch("subprocess.Popen", return_value=proc):
            result = run_download(
                self.track, self.out, "mp3", {},
                popen_hook=hooked.append,
                cancel_check=lambda: True,
            )

        self.assertTrue(stopped.is_set())
        self.assertEqual(hooked, [proc])
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Cancelled")

    def test_stop_process_kills_when_terminate_does_not_end_it(self):
        proc = mock.MagicMock()
        proc.wait.side_effect = [ytdlp_command.subprocess.TimeoutExpired("yt-dlp", 5), -9]
        ytdlp_command._stop_process(proc)
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()

    def test_unexplained_failure_reports_exit_code(self):
        with mock.patch("subprocess.Popen", return_value=_fake_proc(2, "[info] x\n")):
            result = run_download(self.track, self.out, "mp3", {})
        self.assertEqual(result.error, "yt-dlp exited with code 2")


class TestExtraArgsWarning(unittest.TestCase):
    def test_unparseable_extra_args_logs_a_warning(self):
        with mock.patch.object(ytdlp_args, "log_warning") as warn:
            args = ytdlp_args.build_extra_ytdlp_args({"ytdlp_extra_args": '--cookies "unterminated'})
        self.assertEqual(args, [])
        warn.assert_called_once()


class TestCookiesAndRuntime(unittest.TestCase):
    COOKIES = {"ytdlp_extra_args": "--cookies-from-browser firefox --limit-rate 1M"}

    def test_cookies_get_a_js_runtime(self):
        with mock.patch.object(ytdlp_command, "find_js_runtime", return_value=("node", r"C:\node\node.exe")):
            args = ytdlp_command.resolve_extra_args(self.COOKIES)
        self.assertEqual(args[-2:], ["--js-runtimes", r"node:C:\node\node.exe"])
        self.assertIn("--cookies-from-browser", args)

    def test_cookies_dropped_without_a_runtime(self):
        with mock.patch.object(ytdlp_command, "find_js_runtime", return_value=None), \
             mock.patch.object(ytdlp_command, "log_warning") as warn:
            args = ytdlp_command.resolve_extra_args(self.COOKIES)
        self.assertEqual(args, ["--limit-rate", "1M"])
        warn.assert_called_once()

    def test_no_cookies_leaves_args_alone(self):
        with mock.patch.object(ytdlp_command, "find_js_runtime") as find:
            args = ytdlp_command.resolve_extra_args({"ytdlp_extra_args": "--limit-rate 1M"})
        self.assertEqual(args, ["--limit-rate", "1M"])
        find.assert_not_called()

    def test_old_node_is_not_used(self):
        old = mock.Mock(stdout="v18.19.0\n")
        with mock.patch.object(ytdlp_command.subprocess, "run", return_value=old):
            self.assertFalse(ytdlp_command._node_is_supported("node"))


class TestRetries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        NO_FFMPEG.start()
        self.addCleanup(NO_FFMPEG.stop)
        self.track = {"artist": "Artist A", "track": "Song One (Remastered 2011)", "duration_ms": 200000}

    def test_retries_other_clients_then_simpler_title(self):
        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append(cmd)
            if len(calls) == 3:
                with open(os.path.join(self.tmp.name, "Artist A - Song One (Remastered 2011).mp3"), "w") as f:
                    f.write("audio")
            return _fake_proc(0, "")

        with mock.patch("subprocess.Popen", side_effect=fake_popen):
            result = run_download(self.track, self.tmp.name, "mp3", {})

        self.assertTrue(result.success)
        self.assertNotIn("--extractor-args", calls[0])
        self.assertEqual(_flag_value(calls[1], "--extractor-args"), ytdlp_command.RETRY_PLAYER_CLIENTS)
        self.assertEqual(calls[2][1], "ytsearch5:Artist A - Song One")

    def test_final_errors_are_not_retried(self):
        output = "ERROR: HTTP Error 429: Too Many Requests\n"
        with mock.patch("subprocess.Popen", return_value=_fake_proc(1, output)) as popen:
            result = run_download(self.track, self.tmp.name, "mp3", {})
        self.assertEqual(popen.call_count, 1)
        self.assertIn("429", result.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
