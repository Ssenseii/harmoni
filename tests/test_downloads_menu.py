"""Tests for the CLI downloads menu batch download and legacy playlists file."""
import os
import sys
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(THIS_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import menus.downloads_menu as downloads_menu


class TestDownloadsMenu(unittest.TestCase):
    def test_batch_download_saves_resume_progress(self):
        seen = {}

        async def fake_batch(tracks, output_dir, audio_format, **kwargs):
            seen.update(kwargs, tracks=tracks)
            return []

        choices = iter(["Download all pending (batch async) - Works with CSV and JSON sources", "Back"])
        select = mock.Mock()
        select.return_value.ask.side_effect = lambda: next(choices)
        pending = [{"artist": "A", "track": "T"}]
        cfg = {"output_dir": "out", "audio_format": "mp3"}
        with mock.patch.object(downloads_menu.questionary, "select", select), \
             mock.patch.object(downloads_menu, "load_primary_tracks", return_value=pending), \
             mock.patch.object(downloads_menu, "check_downloaded_files", return_value=([], pending)), \
             mock.patch.object(downloads_menu, "batch_download", fake_batch), \
             mock.patch.object(downloads_menu, "log_info"):
            downloads_menu.downloads_menu(cfg)
        self.assertTrue(seen.get("save_progress_first"))
        self.assertIs(seen.get("config"), cfg)
        self.assertEqual(seen.get("tracks"), pending)

    def test_legacy_playlists_file_has_tracks(self):
        example = os.path.join(REPO_ROOT, "data", "playlists.example.json")
        playlists = downloads_menu._load_legacy_playlists({"playlists_file": example})
        self.assertEqual([p["name"] for p in playlists], ["Example Playlist"])
        self.assertEqual(
            [(t["artist"], t["track"]) for t in playlists[0]["tracks"]],
            [("Example Artist", "First Example Song"), ("Another Example Artist", "Second Example Song")],
        )


if __name__ == "__main__":
    unittest.main()
