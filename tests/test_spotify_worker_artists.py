import os
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in os.sys.path:
    os.sys.path.insert(0, THIS_DIR)
    os.sys.path.insert(0, os.path.dirname(THIS_DIR))

from spotify_api.data_loader import SpotifyDataLoader

normalize = SpotifyDataLoader._normalize_artist_list


class TestArtistNames(unittest.TestCase):
    def test_single_artist(self):
        self.assertEqual(normalize([{"name": "Artist A"}]), "Artist A")

    def test_multiple_artists_are_joined(self):
        self.assertEqual(normalize([{"name": "Artist A"}, {"name": "Artist B"}]), "Artist A, Artist B")

    def test_no_artists_is_empty(self):
        self.assertEqual(normalize([]), "")

    def test_missing_artists_is_empty(self):
        self.assertEqual(normalize(None), "")

    def test_artist_with_none_name_does_not_crash(self):
        # Spotify can return an artist entry with "name": None for removed or unavailable artists.
        self.assertEqual(normalize([{"name": None}]), "")

    def test_mix_of_none_and_valid_names(self):
        self.assertEqual(normalize([{"name": None}, {"name": "Artist B"}]), "Artist B")

    def test_track_without_artist_names_is_dropped(self):
        track = {"id": "t1", "name": "Song", "artists": [{"name": None}]}
        self.assertIsNone(SpotifyDataLoader._normalize_track(track))


if __name__ == "__main__":
    unittest.main()
