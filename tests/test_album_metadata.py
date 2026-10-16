import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

# Ensure local imports work when running this file directly.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in os.sys.path:
    os.sys.path.insert(0, THIS_DIR)

from downloader import metadata as md
from spotify_api.data_loader import SpotifyDataLoader

from test_spotify_album_search import RecordingClient


ALBUM = {
    "id": "alb1",
    "name": "Hozier (Special Edition)",
    "artists": [{"name": "Hozier"}],
    "total_tracks": 17,
    "release_date": "2014-09-19",
    "images": [{"url": "https://img/large"}],
}

TRACK = {
    "id": "t1",
    "name": "Take Me to Church",
    "artists": [{"name": "Hozier"}],
    "album": ALBUM,
    "track_number": 1,
    "disc_number": 1,
    "duration_ms": 241000,
}

# What SpotifyDataLoader produces for TRACK; used as the queue/tagger input.
SPOTIFY_TRACK = {
    "artist": "Hozier",
    "track": "Take Me to Church",
    "album": "Hozier (Special Edition)",
    "album_artist": "Hozier",
    "release_date": "2014-09-19",
    "track_number": 1,
    "disc_number": 1,
    "total_tracks": 17,
}


class TestSpotifyAlbumFields(unittest.TestCase):
    def test_normalize_track_includes_release_fields(self):
        t = SpotifyDataLoader._normalize_track(TRACK)
        self.assertEqual(t["album_artist"], "Hozier")
        self.assertEqual(t["track_number"], 1)
        self.assertEqual(t["disc_number"], 1)
        self.assertEqual(t["total_tracks"], 17)

    def test_normalize_track_skips_nameless_artists(self):
        t = SpotifyDataLoader._normalize_track({**TRACK, "artists": [{"name": None}, {"name": "Hozier"}]})
        self.assertEqual(t["artist"], "Hozier")

    def test_load_album_tracks_fills_album_artist_and_total(self):
        simplified = {k: v for k, v in TRACK.items() if k != "album"}
        client = RecordingClient([{"items": [simplified], "total": 1}])
        album = SpotifyDataLoader._normalize_album(ALBUM)
        tracks = SpotifyDataLoader(client).load_album_tracks(album)
        self.assertEqual(tracks[0]["album_artist"], "Hozier")
        self.assertEqual(tracks[0]["total_tracks"], 17)
        self.assertEqual(tracks[0]["track_number"], 1)


class TestTagMetadata(unittest.TestCase):
    def test_release_fields_survive_normalize_and_template(self):
        meta = md.apply_template(md.correct_metadata(md.normalize_track_metadata(SPOTIFY_TRACK)), "basic")
        self.assertEqual(meta["albumartist"], "Hozier")
        self.assertEqual(meta["tracknumber"], "1/17")
        self.assertEqual(meta["discnumber"], "1")

    def test_tracknumber_without_total(self):
        meta = md.normalize_track_metadata({**SPOTIFY_TRACK, "total_tracks": None})
        self.assertEqual(meta["tracknumber"], "1")


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required to generate audio fixtures")
class TestEmbedReleaseTags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _make(self, ext):
        path = os.path.join(self.tmp.name, f"t.{ext}")
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "0.2", path],
            check=True,
        )
        return path

    def _embed(self, path):
        # The album is known, so the per-track MusicBrainz guess must not run.
        with mock.patch.object(md, "lookup_musicbrainz", side_effect=AssertionError("MB called")), \
             mock.patch.object(md, "lookup_musicbrainz_with_config", side_effect=AssertionError("MB called")):
            self.assertTrue(md.embed_track_metadata(path, SPOTIFY_TRACK, template="basic", allow_musicbrainz=True))

    def test_mp3(self):
        from mutagen.easyid3 import EasyID3
        path = self._make("mp3")
        self._embed(path)
        tags = EasyID3(path)
        self.assertEqual(tags["album"], ["Hozier (Special Edition)"])
        self.assertEqual(tags["albumartist"], ["Hozier"])
        self.assertEqual(tags["tracknumber"], ["1/17"])
        self.assertEqual(tags["discnumber"], ["1"])

    def test_m4a(self):
        from mutagen.mp4 import MP4
        path = self._make("m4a")
        self._embed(path)
        tags = MP4(path)
        self.assertEqual(tags["\xa9alb"], ["Hozier (Special Edition)"])
        self.assertEqual(tags["aART"], ["Hozier"])
        self.assertEqual(tags["trkn"], [(1, 17)])
        self.assertEqual(tags["disk"], [(1, 0)])

    def test_flac(self):
        from mutagen.flac import FLAC
        path = self._make("flac")
        self._embed(path)
        tags = FLAC(path)
        self.assertEqual(tags["album"], ["Hozier (Special Edition)"])
        self.assertEqual(tags["albumartist"], ["Hozier"])
        self.assertEqual(tags["tracknumber"], ["1/17"])
        self.assertEqual(tags["discnumber"], ["1"])


if __name__ == "__main__":
    unittest.main()
