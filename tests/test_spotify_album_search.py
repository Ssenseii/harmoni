import os
import unittest

# Ensure local imports work when running this file directly.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in os.sys.path:
    os.sys.path.insert(0, THIS_DIR)

from spotify_api.client import SpotifyClient
from spotify_api.data_loader import SpotifyDataLoader


class RecordingClient(SpotifyClient):
    """SpotifyClient whose HTTP layer returns canned pages and records calls."""

    def __init__(self, pages):
        super().__init__({})
        self.pages = list(pages)
        self.calls = []

    def request_json(self, method, path, *, params=None, **kwargs):
        self.calls.append((method, path, dict(params or {})))
        return self.pages.pop(0) if self.pages else {}


ALBUM = {
    "id": "alb1",
    "name": "OK Computer",
    "artists": [{"name": "Radiohead"}],
    "total_tracks": 12,
    "release_date": "1997-05-21",
    "images": [{"url": "https://img/large"}, {"url": "https://img/small"}],
    "uri": "spotify:album:alb1",
}


class TestSpotifyClientAlbumEndpoints(unittest.TestCase):
    def test_search_albums_request(self):
        client = RecordingClient([{"albums": {"items": []}}])
        client.search_albums("ok computer", limit=10, offset=0)
        method, path, params = client.calls[0]
        self.assertEqual((method, path), ("GET", "/search"))
        self.assertEqual(params["q"], "ok computer")
        self.assertEqual(params["type"], "album")
        self.assertEqual(params["limit"], 10)

    def test_search_albums_caps_limit_at_spotify_max(self):
        # Spotify rejects limit > 10 on /search for this app with "400 Invalid limit".
        client = RecordingClient([{"albums": {"items": []}}])
        client.search_albums("x", limit=50)
        self.assertEqual(client.calls[0][2]["limit"], 10)

    def test_album_tracks_request(self):
        client = RecordingClient([{"items": []}])
        client.album_tracks("alb1", limit=50, offset=50)
        method, path, params = client.calls[0]
        self.assertEqual((method, path), ("GET", "/albums/alb1/tracks"))
        self.assertEqual((params["limit"], params["offset"]), (50, 50))


class TestSpotifyDataLoaderAlbums(unittest.TestCase):
    def test_search_albums_normalizes_and_skips_nulls(self):
        client = RecordingClient([{"albums": {"items": [ALBUM, None, {"id": None, "name": "x"}]}}])
        albums = SpotifyDataLoader(client).search_albums("ok computer")
        self.assertEqual(len(albums), 1)
        a = albums[0]
        self.assertEqual(a["kind"], "album")
        self.assertEqual(a["id"], "alb1")
        self.assertEqual(a["title"], "OK Computer")
        self.assertEqual(a["artist"], "Radiohead")
        self.assertEqual(a["name"], "Radiohead - OK Computer")
        self.assertEqual(a["tracks_total"], 12)
        self.assertEqual(a["release_date"], "1997-05-21")
        self.assertEqual(a["image_url"], "https://img/large")

    def test_search_albums_blank_query_makes_no_request(self):
        client = RecordingClient([])
        self.assertEqual(SpotifyDataLoader(client).search_albums("   "), [])
        self.assertEqual(client.calls, [])

    def test_load_album_tracks_pages_and_fills_album_name(self):
        # Album track objects are "simplified" and carry no album info.
        t1 = {"id": "t1", "name": "Airbag", "artists": [{"name": "Radiohead"}], "duration_ms": 1}
        t2 = {"id": "t2", "name": "Lucky", "artists": [{"name": "Radiohead"}], "duration_ms": 2}
        local = {"id": None, "name": "x", "artists": [{"name": "y"}], "is_local": True}
        client = RecordingClient([
            {"items": [t1, local], "total": 3},
            {"items": [t2], "total": 3},
        ])
        tracks = SpotifyDataLoader(client).load_album_tracks(ALBUM, limit=2)

        self.assertEqual([t["track"] for t in tracks], ["Airbag", "Lucky"])
        self.assertTrue(all(t["album"] == "OK Computer" for t in tracks))
        self.assertTrue(all(t["artist"] == "Radiohead" for t in tracks))
        self.assertEqual(tracks[0]["spotify_id"], "t1")
        self.assertEqual(tracks[0]["release_date"], "1997-05-21")
        self.assertEqual([c[2]["offset"] for c in client.calls], [0, 2])


if __name__ == "__main__":
    unittest.main()
