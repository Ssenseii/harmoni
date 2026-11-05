"""Tests for config path anchoring, corrupt config recovery, reset_to_defaults, new config keys and data paths."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in os.sys.path:
    os.sys.path.insert(0, THIS_DIR)
    os.sys.path.insert(0, os.path.dirname(THIS_DIR))

import config
import constants
from managers import backup_manager, sync_manager
from utils import jsonio


class _TempConfig(unittest.TestCase):
    """Point config.CONFIG_PATH at a temp file for each test."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name
        self.path = os.path.join(self.tmp, "config.json")
        patcher = mock.patch.object(config, "CONFIG_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        warn = mock.patch.object(jsonio, "log_warning")
        warn.start()
        self.addCleanup(warn.stop)
        self.addCleanup(self._td.cleanup)

    def write_raw(self, data):
        """Write data to the temp config file.

        @param data: A dict to dump as JSON, or a str written verbatim.
        """
        with open(self.path, "w", encoding="utf-8") as f:
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f)

    def read_raw(self):
        """Return the temp config file parsed as JSON."""
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)


class TestResolveAppPath(unittest.TestCase):
    def test_relative_path_is_joined_onto_app_dir(self):
        self.assertEqual(
            config.resolve_app_path("data/tracks.json"),
            os.path.normpath(os.path.join(config.APP_DIR, "data", "tracks.json")),
        )

    def test_absolute_path_is_unchanged(self):
        absolute = os.path.abspath(os.path.join(os.sep, "music", "lib"))
        self.assertEqual(config.resolve_app_path(absolute), absolute)

    def test_empty_path_is_unchanged(self):
        self.assertEqual(config.resolve_app_path(""), "")


class TestLoadConfig(_TempConfig):
    def test_corrupt_config_falls_back_to_defaults_and_keeps_copy(self):
        self.write_raw("{ this is not json")
        cfg = config.load_config()
        self.assertEqual(cfg["audio_format"], config.DEFAULT_CONFIG["audio_format"])
        self.assertTrue(os.path.exists(self.path + ".corrupt"))
        self.assertFalse(os.path.exists(self.path))

    def test_missing_config_still_raises(self):
        with self.assertRaises(FileNotFoundError):
            config.load_config()

    def test_relative_path_keys_are_resolved(self):
        self.write_raw({"tracks_file": "data/tracks.json", "output_dir": "music"})
        cfg = config.load_config()
        for key in config.PATH_CONFIG_KEYS:
            self.assertTrue(os.path.isabs(cfg[key]), key)
        self.assertEqual(cfg["output_dir"], os.path.normpath(os.path.join(config.APP_DIR, "music")))

    def test_absolute_path_keys_are_kept(self):
        absolute = os.path.join(self.tmp, "Music")
        self.write_raw({"output_dir": absolute})
        self.assertEqual(config.load_config()["output_dir"], absolute)

    def test_executable_paths_are_not_resolved(self):
        self.write_raw({"ffmpeg_path": "ffmpeg", "ytdlp_path": ""})
        cfg = config.load_config()
        self.assertEqual(cfg["ffmpeg_path"], "ffmpeg")
        self.assertEqual(cfg["ytdlp_path"], "")

    def test_save_after_load_keeps_relative_paths_on_disk(self):
        self.write_raw({"tracks_file": "data/tracks.json", "audio_format": "flac"})
        cfg = config.load_config()
        cfg["audio_format"] = "mp3"
        config.save_config(cfg)
        raw = self.read_raw()
        self.assertEqual(raw["tracks_file"], "data/tracks.json")
        self.assertEqual(raw["output_dir"], "music")
        self.assertEqual(raw["audio_format"], "mp3")

    def test_save_keeps_user_chosen_absolute_path(self):
        self.write_raw({"output_dir": "music"})
        cfg = config.load_config()
        chosen = os.path.join(self.tmp, "Elsewhere")
        cfg["output_dir"] = chosen
        config.save_config(cfg)
        self.assertEqual(self.read_raw()["output_dir"], chosen)

    def test_save_config_is_atomic(self):
        self.write_raw({"audio_format": "flac"})
        with mock.patch.object(config, "write_json_atomic") as atomic:
            config.save_config({"audio_format": "mp3"})
        atomic.assert_called_once()
        self.assertEqual(atomic.call_args[0][0], self.path)


class TestResetToDefaults(_TempConfig):
    def test_reset_keeps_spotify_keys(self):
        self.write_raw({
            "spotify_client_id": "abc123",
            "spotify_redirect_uri": "http://127.0.0.1:9999/cb",
            "audio_format": "flac",
            "output_dir": "/somewhere",
        })
        ok, _ = config.reset_to_defaults()
        self.assertTrue(ok)
        raw = self.read_raw()
        self.assertEqual(raw["spotify_client_id"], "abc123")
        self.assertEqual(raw["spotify_redirect_uri"], "http://127.0.0.1:9999/cb")
        self.assertEqual(raw["audio_format"], config.DEFAULT_CONFIG["audio_format"])
        self.assertEqual(raw["output_dir"], config.DEFAULT_CONFIG["output_dir"])


class TestConstantsPaths(unittest.TestCase):
    def test_data_paths_are_anchored_to_app_dir(self):
        self.assertEqual(constants.APP_DIR, config.APP_DIR)
        for path in (constants.FAILED_FILE, constants.PROGRESS_FILE, constants.LOG_FILE):
            self.assertTrue(os.path.isabs(path), path)
            self.assertEqual(os.path.commonpath([path, constants.APP_DIR]), constants.APP_DIR)

    def test_frozen_app_dir_uses_executable_folder(self):
        exe = os.path.join(os.path.abspath(os.sep), "Apps", "HARMONI", "HARMONI.exe")
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", exe):
            self.assertEqual(constants._app_dir(), os.path.dirname(exe))

    def test_backup_and_sync_paths_live_under_app_dir(self):
        app_dir = os.path.normcase(constants.APP_DIR)
        paths = [backup_manager.BACKUP_DIR, sync_manager.SYNC_STATE_FILE, *backup_manager.BACKUP_TARGETS]
        for path in paths:
            self.assertTrue(os.path.isabs(path), path)
            self.assertTrue(os.path.normcase(path).startswith(app_dir), path)


class TestTuningKeys(unittest.TestCase):
    def test_defaults_include_tuning_keys_and_validate(self):
        self.assertEqual(config.DEFAULT_CONFIG["match_duration_tolerance"], 15)
        self.assertEqual(config.DEFAULT_CONFIG["spotify_max_retry_after"], 30)
        ok, errors = config.validate_config(dict(config.DEFAULT_CONFIG))
        self.assertTrue(ok, errors)

    def test_out_of_range_tuning_keys_are_rejected(self):
        cfg = dict(config.DEFAULT_CONFIG, match_duration_tolerance=-1, spotify_max_retry_after="x")
        ok, errors = config.validate_config(cfg)
        self.assertFalse(ok)
        self.assertTrue(any("match_duration_tolerance" in e for e in errors))
        self.assertTrue(any("spotify_max_retry_after" in e for e in errors))


class TestChooseAudioFormat(unittest.TestCase):
    def test_saves_through_config_module_not_cwd(self):
        from tools import choose_audio_format as module

        cfg = {"audio_format": "mp3"}
        select = mock.Mock()
        select.return_value.ask.return_value = ".flac"
        with tempfile.TemporaryDirectory() as td:
            old_cwd = os.getcwd()
            os.chdir(td)
            try:
                with mock.patch.object(module.questionary, "select", select), \
                     mock.patch.object(module, "save_config") as save, \
                     mock.patch.object(module, "log_success"):
                    module.choose_audio_format(cfg)
                self.assertFalse(os.path.exists(os.path.join(td, "config.json")))
            finally:
                os.chdir(old_cwd)
        save.assert_called_once_with(cfg)
        self.assertEqual(cfg["audio_format"], "flac")


class TestManagersUseJsonio(unittest.TestCase):
    def setUp(self):
        warn = mock.patch.object(jsonio, "log_warning")
        warn.start()
        self.addCleanup(warn.stop)

    def test_corrupt_sync_state_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            state_file = os.path.join(td, "data", "sync_state.json")
            os.makedirs(os.path.dirname(state_file))
            with open(state_file, "w", encoding="utf-8") as f:
                f.write("{broken")
            with mock.patch.object(sync_manager, "SYNC_STATE_FILE", state_file):
                self.assertEqual(sync_manager.load_sync_state(), {"synced_files": {}, "last_sync": None})
                self.assertTrue(os.path.exists(state_file + ".corrupt"))
                sync_manager.save_sync_state({"synced_files": {"a.csv": {}}, "last_sync": "x"})
                self.assertEqual(sync_manager.load_sync_state()["last_sync"], "x")

    def test_sync_does_not_silently_overwrite_corrupt_tracks_json(self):
        with tempfile.TemporaryDirectory() as td:
            exportify = os.path.join(td, "exportify")
            os.makedirs(exportify)
            with open(os.path.join(exportify, "p.csv"), "w", encoding="utf-8") as f:
                f.write("x")
            tracks_file = os.path.join(td, "tracks.json")
            with open(tracks_file, "w", encoding="utf-8") as f:
                f.write('{"tracks": [ {"artist": "A"')
            cfg = {"exportify_watch_folder": exportify, "tracks_file": tracks_file, "auto_backup": False}
            new_track = {"artist": "B", "track": "T", "album": "", "uri": ""}
            with mock.patch.object(sync_manager, "SYNC_STATE_FILE", os.path.join(td, "s.json")), \
                    mock.patch.object(sync_manager, "load_exportify_tracks", return_value=[new_track]), \
                    mock.patch.object(sync_manager, "log_info"):
                sync_manager.sync_exportify_folder(cfg)
            with open(tracks_file + ".corrupt", encoding="utf-8") as f:
                self.assertEqual(f.read(), '{"tracks": [ {"artist": "A"')
            with open(tracks_file, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["tracks"][0]["artist"], "B")

    def test_restore_backup_writes_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            backup = os.path.join(td, "tracks_1.json")
            target = os.path.join(td, "out", "tracks.json")
            with open(backup, "w", encoding="utf-8") as f:
                json.dump({"tracks": [1]}, f)
            with mock.patch.object(backup_manager, "log_info"), \
                    mock.patch.object(backup_manager, "write_json_atomic", wraps=jsonio.write_json_atomic) as atomic:
                self.assertTrue(backup_manager.restore_backup(backup, target))
            atomic.assert_called_once()
            with open(target, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"tracks": [1]})

    def test_restore_rejects_corrupt_backup(self):
        with tempfile.TemporaryDirectory() as td:
            backup = os.path.join(td, "tracks_1.json")
            target = os.path.join(td, "tracks.json")
            with open(backup, "w", encoding="utf-8") as f:
                f.write("nope")
            with mock.patch.object(backup_manager, "log_error"):
                self.assertFalse(backup_manager.restore_backup(backup, target))
            self.assertFalse(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
