import os
import unittest

# Ensure local imports work when running this file directly.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in os.sys.path:
    os.sys.path.insert(0, THIS_DIR)

from spotify_api.data_loader import SpotifyDataLoader


class FakeSpotifyClient:
    def __init__(self, *, total_liked: int = 120, total_playlist_tracks: int = 215, total_playlists: int = 87):
        self.total_liked = total_liked
        self.total_playlist_tracks = total_playlist_tracks
        self.total_playlists = total_playlists

    def me(self):
        return {"id": "me", "display_name": "Me"}

    def current_user_saved_tracks(self, *, limit: int = 50, offset: int = 0):
        remaining = max(0, self.total_liked - offset)
        n = min(int(limit), remaining)
        items = []
        for i in range(n):
            idx = offset + i
            items.append(
                {
                    "added_at": "2020-01-01T00:00:00Z",
                    "track": {
                        "id": f"liked{idx}",
                        "uri": f"spotify:track:liked{idx}",
                        "name": f"Liked Song {idx}",
                        "artists": [{"name": "Artist"}],
                        "album": {"name": "Album", "release_date": "2020-01-01"},
                        "duration_ms": 180000,
                        "explicit": False,
                        "popularity": 50,
                        "external_ids": {"isrc": f"ISRC{idx}"},
                        "external_urls": {"spotify": f"https://open.spotify.com/track/liked{idx}"},
                    },
                }
            )
        return {"items": items, "total": self.total_liked, "limit": limit, "offset": offset}

    def playlist_items(self, playlist_id: str, *, limit: int = 100, offset: int = 0):
        remaining = max(0, self.total_playlist_tracks - offset)
        n = min(int(limit), remaining)
        items = []
        for i in range(n):
            idx = offset + i
            items.append(
                {
                    "added_at": "2020-01-01T00:00:00Z",
                    "item": {
                        "id": f"pl{idx}",
                        "uri": f"spotify:track:pl{idx}",
                        "name": f"Playlist Song {idx}",
                        "artists": [{"name": "Artist"}],
                        "album": {"name": "Album", "release_date": "2020-01-01"},
                        "duration_ms": 180000,
                        "explicit": False,
                        "popularity": 50,
                        "external_ids": {"isrc": f"ISRCPL{idx}"},
                        "external_urls": {"spotify": f"https://open.spotify.com/track/pl{idx}"},
                    },
                }
            )
        return {"items": items, "total": self.total_playlist_tracks, "limit": limit, "offset": offset}

    def current_user_playlists(self, *, limit: int = 50, offset: int = 0):
        remaining = max(0, self.total_playlists - offset)
        n = min(int(limit), remaining)
        items = []
        for i in range(n):
            idx = offset + i
            items.append(
                {
                    "id": f"playlist{idx}",
                    "name": f"Playlist {idx}",
                    "items": {"total": 123},
                    "owner": {"id": "me", "display_name": "Me"},
                    "public": False,
                }
            )
        return {"items": items, "total": self.total_playlists, "limit": limit, "offset": offset}


class TestSpotifyDataLoaderLimits(unittest.TestCase):
    def test_load_liked_songs_max_tracks_caps_results(self):
        loader = SpotifyDataLoader(FakeSpotifyClient(total_liked=120))
        tracks = loader.load_liked_songs(max_tracks=60)
        self.assertEqual(len(tracks), 60)
        self.assertEqual(tracks[0]["spotify_id"], "liked0")
        self.assertEqual(tracks[-1]["spotify_id"], "liked59")
        self.assertTrue(all("artist" in t and "track" in t for t in tracks))

    def test_load_playlist_tracks_max_tracks_caps_results(self):
        loader = SpotifyDataLoader(FakeSpotifyClient(total_playlist_tracks=215))
        tracks = loader.load_playlist_tracks("any", max_tracks=125)
        self.assertEqual(len(tracks), 125)
        self.assertEqual(tracks[0]["spotify_id"], "pl0")
        self.assertEqual(tracks[-1]["spotify_id"], "pl124")

    def test_list_all_playlists_max_playlists_caps_results(self):
        loader = SpotifyDataLoader(FakeSpotifyClient(total_playlists=87))
        pls = loader.list_all_playlists(limit=50, max_playlists=20)
        self.assertEqual(len(pls), 20)
        self.assertEqual(pls[0]["id"], "playlist0")
        self.assertEqual(pls[-1]["id"], "playlist19")
        self.assertEqual(pls[0]["tracks_total"], 123)
        self.assertTrue(pls[0]["fetchable"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
