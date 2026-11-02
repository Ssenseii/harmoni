"""Tests for reading public Spotify playlists, albums and tracks from the embed page, with no network."""
import json
import os
import sys
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(THIS_DIR) not in sys.path:
    sys.path.insert(0, os.path.dirname(THIS_DIR))

from spotify_api.public_embed import PublicSpotifyError, fetch_public_tracks, parse_spotify_link

PLAYLIST_ID = "5tnqBxQJKiAqAjnfETfD8r"


def _page(entity):
    """Wrap an entity in the embed page's __NEXT_DATA__ script.

    @param entity: The data the page carries.
    """
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


class TestParseLink(unittest.TestCase):
    def test_accepts_links_and_uris(self):
        cases = {
            f"https://open.spotify.com/playlist/{PLAYLIST_ID}?si=078a77a614f14003": ("playlist", PLAYLIST_ID),
            f"https://open.spotify.com/intl-de/album/{PLAYLIST_ID}": ("album", PLAYLIST_ID),
            f"spotify:track:{PLAYLIST_ID}": ("track", PLAYLIST_ID),
        }
        for link, expected in cases.items():
            self.assertEqual(parse_spotify_link(link), expected, link)

    def test_rejects_other_links(self):
        self.assertIsNone(parse_spotify_link("https://www.youtube.com/watch?v=abc"))
        self.assertIsNone(parse_spotify_link(""))


class TestFetchPublicTracks(unittest.TestCase):
    def test_playlist_tracks_become_track_dicts(self):
        entity = {"name": "Influenced Radio", "trackList": [
            {"title": "Uapiti", "subtitle": "Klipsun, Electrypnose", "duration": 762553,
             "uri": "spotify:track:6pvgyUX1I1Hq0NAi5SqCNU", "isPlayable": True},
            {"title": "Gone", "subtitle": "Someone", "duration": 1000, "uri": "spotify:track:x", "isPlayable": False},
        ]}
        seen = []
        name, tracks = fetch_public_tracks("playlist", PLAYLIST_ID, fetch=lambda url: seen.append(url) or _page(entity))
        self.assertEqual(seen, [f"https://open.spotify.com/embed/playlist/{PLAYLIST_ID}"])
        self.assertEqual(name, "Influenced Radio")
        self.assertEqual(tracks, [{
            "artist": "Klipsun, Electrypnose", "track": "Uapiti", "duration_ms": 762553,
            "uri": "spotify:track:6pvgyUX1I1Hq0NAi5SqCNU", "spotify_id": "6pvgyUX1I1Hq0NAi5SqCNU", "explicit": None,
        }])

    def test_single_track_uses_artist_list(self):
        entity = {"name": "Never Gonna Give You Up", "title": "Never Gonna Give You Up", "duration": 213573,
                  "uri": "spotify:track:4cOdK2wGLETKBW3PvgPWqT", "artists": [{"name": "Rick Astley"}]}
        name, tracks = fetch_public_tracks("track", "4cOdK2wGLETKBW3PvgPWqT", fetch=lambda url: _page(entity))
        self.assertEqual(tracks[0]["artist"], "Rick Astley")

    def test_private_or_missing_page_explains(self):
        with self.assertRaises(PublicSpotifyError):
            fetch_public_tracks("playlist", PLAYLIST_ID, fetch=lambda url: "<html>no data</html>")

    def test_network_error_explains(self):
        def offline(url):
            raise OSError("offline")

        with self.assertRaisesRegex(PublicSpotifyError, "Couldn't reach Spotify"):
            fetch_public_tracks("playlist", PLAYLIST_ID, fetch=offline)


if __name__ == "__main__":
    unittest.main()
