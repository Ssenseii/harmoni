"""Tests for utils.loaders handling of missing data files and both playlists.json shapes."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(THIS_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from utils import loaders

EXAMPLE_PLAYLISTS = os.path.join(REPO_ROOT, "data", "playlists.example.json")
EXAMPLE_TRACKS = os.path.join(REPO_ROOT, "data", "tracks.example.json")


class TestMissingDataFiles(unittest.TestCase):
    def test_missing_tracks_file_is_empty_without_error(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(loaders, "log_error") as log_error, \
             mock.patch.object(loaders, "log_warning") as log_warning:
            self.assertEqual(loaders.load_tracks(os.path.join(td, "tracks.json")), [])
        log_error.assert_not_called()
        self.assertIn("tracks.example.json", log_warning.call_args[0][0])

    def test_missing_playlists_file_is_empty_without_error(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(loaders, "log_error") as log_error, \
             mock.patch.object(loaders, "log_warning"):
            self.assertEqual(loaders.load_playlists(os.path.join(td, "playlists.json")), [])
        log_error.assert_not_called()

    def test_example_tracks_file_loads(self):
        tracks = loaders.load_tracks(EXAMPLE_TRACKS)
        self.assertTrue(tracks)
        self.assertTrue(all(t.get("artist") and t.get("track") for t in tracks))


class TestPlaylistsFileFormats(unittest.TestCase):
    def test_spotify_export_items_shape_loads(self):
        playlists = loaders.load_playlists(EXAMPLE_PLAYLISTS)
        self.assertEqual([p["name"] for p in playlists], ["Example Playlist"])
        first = playlists[0]["tracks"][0]
        self.assertEqual(first["artist"], "Example Artist")
        self.assertEqual(first["track"], "First Example Song")
        self.assertEqual(first["album"], "Example Album")
        self.assertEqual(first["uri"], "spotify:track:0000000000000000000001")

    def test_flat_tracks_shape_still_loads(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "playlists.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"playlists": [{"name": "Flat", "tracks": [{"artist": "A", "track": "T"}]}]}, f)
            playlists = loaders.load_playlists(path)
        self.assertEqual(playlists, [{"name": "Flat", "tracks": [{"artist": "A", "track": "T"}]}])


if __name__ == "__main__":
    unittest.main()
