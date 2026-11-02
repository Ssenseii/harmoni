"""Tests for adding Spotify tracks to the download queue from SpotifyView."""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(THIS_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from gui.views import spotify_view as spotify_view_module


class TestSpotifySingleAdd(unittest.TestCase):
    def test_single_add_passes_full_track(self):
        queue = mock.MagicMock()
        with mock.patch.object(spotify_view_module.SpotifyPKCEAuth, "load_cached_token", return_value=None):
            view = spotify_view_module.SpotifyView({"spotify_cache_tokens": False}, queue)
        self.addCleanup(view.deleteLater)
        track = {"artist": "A", "track": "T", "album": "Al", "duration_ms": 200000}
        view.current_tracks = [track]
        with mock.patch.object(spotify_view_module.queued_notice, "confirm_queued", return_value=False):
            view._add_single_to_queue(0)
        self.assertIs(queue.add_track.call_args.kwargs.get("track_data"), track)


if __name__ == "__main__":
    unittest.main()
