"""Tests for Spotify's February 2026 API shape: items totals, item entries, fetchable playlists and the thin worker."""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
if ROOT_DIR not in os.sys.path:
    os.sys.path.insert(0, ROOT_DIR)

from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

from gui.views import spotify_view as spotify_view_module
from gui.views.spotify_view import NOT_FETCHABLE_TOOLTIP, SpotifyView
from gui.workers.spotify_worker import SpotifyWorker
from spotify_api.client import SessionTokenManager
from spotify_api.data_loader import SpotifyDataLoader, playlist_total
from spotify_api.token_manager import TokenInfo
import menus.downloads_menu as downloads_menu

ME_ID = "me123"


class _Signal:
    """Minimal stand-in for a Qt signal that calls its slots straight away."""

    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in self.slots:
            slot(*args)


class _SyncThread:
    """Runs a FunctionThread's callable synchronously on start()."""

    def __init__(self, fn):
        self.fn = fn
        self.succeeded = _Signal()
        self.failed = _Signal()

    def start(self):
        try:
            result = self.fn()
        except Exception as e:
            self.failed.emit(e)
        else:
            self.succeeded.emit(result)


def _track(idx):
    """Build a Spotify track object.

    @param idx: Number used in the id and name.
    """
    return {
        "id": f"t{idx}",
        "uri": f"spotify:track:t{idx}",
        "name": f"Song {idx}",
        "artists": [{"name": "Artist"}],
        "album": {"name": "Album"},
        "duration_ms": 1000,
    }


def _playlist(pid, owner_id, *, collaborative=False, total=3, legacy=False):
    """Build a playlist object in the Feb 2026 shape, or the legacy "tracks" shape.

    @param pid: Playlist id.
    @param owner_id: Owner's Spotify user id.
    @param collaborative: Spotify's collaborative flag.
    @param total: Item count reported by Spotify.
    @param legacy: Use the pre-2026 "tracks" field instead of "items".
    """
    p = {
        "id": pid,
        "name": f"Playlist {pid}",
        "owner": {"id": owner_id, "display_name": owner_id.title()},
        "collaborative": collaborative,
        "public": False,
        "images": [{"url": f"https://img/{pid}"}],
    }
    p["tracks" if legacy else "items"] = {"total": total}
    return p


class FakeClient:
    """Spotify client stub that pages playlist items and liked songs and records calls."""

    def __init__(self, playlists=None, *, item_total=5, liked_total=3, legacy_items=False):
        """Store the fake account contents.

        @param playlists: Playlist objects returned by /me/playlists.
        @param item_total: Number of entries in every playlist.
        @param liked_total: Number of liked songs.
        @param legacy_items: Return playlist entries under "track" instead of "item".
        """
        self.playlists = playlists or []
        self.item_total = item_total
        self.liked_total = liked_total
        self.legacy_items = legacy_items
        self.item_calls = []
        self.me_calls = 0

    def get_token(self):
        return TokenInfo(access_token="AT", token_type="Bearer", expires_at=9999999999.0)

    def me(self):
        self.me_calls += 1
        return {"id": ME_ID, "display_name": "Me"}

    def current_user_playlists(self, *, limit=50, offset=0):
        page = self.playlists[offset:offset + limit]
        return {"items": page, "total": len(self.playlists)}

    def playlist_items(self, playlist_id, *, limit=100, offset=0):
        self.item_calls.append((playlist_id, offset))
        key = "track" if self.legacy_items else "item"
        n = max(0, min(limit, self.item_total - offset))
        return {"items": [{key: _track(offset + i)} for i in range(n)], "total": self.item_total}

    def current_user_saved_tracks(self, *, limit=50, offset=0):
        n = max(0, min(limit, self.liked_total - offset))
        return {"items": [{"track": _track(offset + i)} for i in range(n)], "total": self.liked_total}


class TestPlaylistTotal(unittest.TestCase):
    def test_reads_items_total(self):
        self.assertEqual(playlist_total(_playlist("a", ME_ID, total=7)), 7)

    def test_falls_back_to_legacy_tracks_total(self):
        self.assertEqual(playlist_total(_playlist("a", ME_ID, total=9, legacy=True)), 9)

    def test_missing_total_is_none(self):
        self.assertIsNone(playlist_total({"id": "x"}))


class TestFetchableFlag(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient([
            _playlist("owned", ME_ID, total=4),
            _playlist("followed", "someone"),
            _playlist("collab", "someone", collaborative=True),
            _playlist("legacy", ME_ID, total=2, legacy=True),
        ])
        self.playlists = {p["id"]: p for p in SpotifyDataLoader(self.client).list_all_playlists()}

    def test_owned_is_fetchable(self):
        p = self.playlists["owned"]
        self.assertTrue(p["fetchable"])
        self.assertEqual(p["owner_id"], ME_ID)
        self.assertEqual(p["tracks_total"], 4)

    def test_followed_is_not_fetchable(self):
        p = self.playlists["followed"]
        self.assertFalse(p["fetchable"])
        self.assertFalse(p["collaborative"])

    def test_collaborative_is_fetchable(self):
        self.assertTrue(self.playlists["collab"]["fetchable"])
        self.assertTrue(self.playlists["collab"]["collaborative"])

    def test_legacy_shape_total(self):
        self.assertEqual(self.playlists["legacy"]["tracks_total"], 2)

    def test_me_fetched_once(self):
        client = FakeClient([_playlist("owned", ME_ID)])
        loader = SpotifyDataLoader(client)
        loader.current_user()
        loader.list_all_playlists()
        self.assertEqual(client.me_calls, 1)


class TestLoaderTracks(unittest.TestCase):
    def test_playlist_items_read_item_field(self):
        tracks = SpotifyDataLoader(FakeClient(item_total=3)).load_playlist_tracks("owned")
        self.assertEqual([t["spotify_id"] for t in tracks], ["t0", "t1", "t2"])

    def test_playlist_items_legacy_track_field(self):
        tracks = SpotifyDataLoader(FakeClient(item_total=2, legacy_items=True)).load_playlist_tracks("owned")
        self.assertEqual(len(tracks), 2)

    def test_liked_songs_still_read_track(self):
        tracks = SpotifyDataLoader(FakeClient(liked_total=3)).load_liked_songs()
        self.assertEqual([t["spotify_id"] for t in tracks], ["t0", "t1", "t2"])

    def test_on_batch_and_should_cancel(self):
        client = FakeClient(item_total=250)
        batches = []
        tracks = SpotifyDataLoader(client).load_playlist_tracks(
            "owned",
            on_batch=lambda batch, total: batches.append((len(batch), total)),
            should_cancel=lambda: len(batches) >= 2,
        )
        self.assertEqual(batches, [(100, 250), (100, 250)])
        self.assertEqual(len(client.item_calls), 2)
        self.assertEqual(len(tracks), 200)

    def test_load_user_playlists_with_tracks_skips_unfetchable(self):
        client = FakeClient([_playlist("owned", ME_ID), _playlist("followed", "someone")], item_total=2)
        out = SpotifyDataLoader(client).load_user_playlists_with_tracks(include_liked_songs=True)
        self.assertEqual([p["name"] for p in out], ["Liked Songs", "Playlist owned"])
        self.assertEqual(len(out[1]["tracks"]), 2)
        self.assertEqual({pid for pid, _ in client.item_calls}, {"owned"})


class TestWorker(unittest.TestCase):
    def _worker(self, client, task, **args):
        """Build a worker for a task without starting its thread.

        @param client: Client passed to the worker.
        @param task: Task name.
        @param args: Task arguments.
        """
        worker = SpotifyWorker({}, client=client)
        worker._task = task
        worker._task_args = args
        return worker

    def test_streams_batches_and_finishes(self):
        client = FakeClient(item_total=250)
        worker = self._worker(client, "playlist_tracks", playlist_id="owned", playlist_name="Owned")
        batches, loaded = [], []
        worker.tracks_batch.connect(lambda pid, b: batches.append((pid, len(b))))
        worker.tracks_loaded.connect(lambda pid, t: loaded.append((pid, len(t))))
        worker.run()
        self.assertEqual(batches, [("owned", 100), ("owned", 100), ("owned", 50)])
        self.assertEqual(loaded, [("owned", 250)])

    def test_cancel_stops_between_pages(self):
        client = FakeClient(item_total=250)
        worker = self._worker(client, "playlist_tracks", playlist_id="owned", playlist_name="Owned")
        loaded = []
        worker.tracks_batch.connect(lambda pid, b: worker.cancel())
        worker.tracks_loaded.connect(lambda pid, t: loaded.append(pid))
        worker.run()
        self.assertEqual(len(client.item_calls), 1)
        self.assertEqual(loaded, [])

    def test_playlists_carry_fetchable(self):
        client = FakeClient([_playlist("owned", ME_ID), _playlist("followed", "someone")])
        worker = self._worker(client, "playlists")
        seen = []
        worker.playlists_loaded.connect(seen.append)
        worker.run()
        self.assertEqual([(p["id"], p["fetchable"]) for p in seen[0]], [("owned", True), ("followed", False)])
        self.assertEqual(seen[0][0]["image_url"], "https://img/owned")

    def test_liked_songs_stream(self):
        worker = self._worker(FakeClient(liked_total=3), "liked_songs")
        batches, loaded = [], []
        worker.tracks_batch.connect(lambda pid, b: batches.append(pid))
        worker.liked_songs_loaded.connect(lambda t: loaded.append(len(t)))
        worker.run()
        self.assertEqual(batches, ["__liked_songs__"])
        self.assertEqual(loaded, [3])

    def test_progress_reports_page_total(self):
        cases = [
            (FakeClient(item_total=250), "playlist_tracks", {"playlist_id": "owned", "playlist_name": "Owned"}, 250),
            (FakeClient(liked_total=3), "liked_songs", {}, 3),
            (FakeClient([_playlist(str(i), ME_ID) for i in range(60)]), "playlists", {}, 60),
        ]
        for client, task, args, total in cases:
            with self.subTest(task=task):
                worker = self._worker(client, task, **args)
                progress = []
                worker.progress.connect(lambda message, current, t: progress.append((current, t)))
                worker.run()
                self.assertEqual(progress[-1], (total, total))

    def test_no_token_reports_not_connected(self):
        client = mock.Mock()
        client.get_token.side_effect = RuntimeError("No Spotify token available.")
        worker = self._worker(client, "playlists")
        seen = []
        worker.error_status.connect(lambda status, message: seen.append((status, message)))
        worker.run()
        self.assertEqual(seen, [(401, "Not connected to Spotify. Please log in first.")])
        client.current_user_playlists.assert_not_called()


class TestSessionTokenManager(unittest.TestCase):
    def test_keeps_token_in_memory_without_disk_cache(self):
        tm = SessionTokenManager(cache_path=os.path.join(THIS_DIR, "_never_written_tokens.json"))
        cfg = {"spotify_cache_tokens": False}
        token = TokenInfo(access_token="AT", token_type="Bearer", expires_at=9999999999.0)
        self.assertFalse(tm.save(cfg, token))
        self.assertEqual(tm.load(cfg), token)
        self.assertFalse(os.path.exists(tm.cache_path))
        tm.clear()
        self.assertIsNone(tm.load(cfg))


class TestSpotifyView(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(spotify_view_module.SpotifyPKCEAuth, "load_cached_token", return_value=None):
            self.view = SpotifyView({"spotify_cache_tokens": False}, mock.MagicMock())
        self.addCleanup(self.view.deleteLater)
        self.owned = {"id": "owned", "name": "Owned", "tracks_total": 3, "fetchable": True}
        self.followed = {"id": "followed", "name": "Followed", "tracks_total": 5, "fetchable": False}
        self.view._on_playlists_loaded([self.owned, self.followed])

    def test_followed_playlist_has_explaining_tooltip(self):
        self.assertEqual(self.view.playlist_list.item(1).toolTip(), NOT_FETCHABLE_TOOLTIP)
        self.assertEqual(self.view.playlist_list.item(0).toolTip(), "")

    def test_followed_playlist_loads_from_public_page(self):
        tracks = [{"artist": "A", "track": "T"}]
        with mock.patch.object(spotify_view_module, "SpotifyWorker") as worker_cls, \
             mock.patch.object(spotify_view_module, "FunctionThread", _SyncThread), \
             mock.patch.object(spotify_view_module, "fetch_public_tracks", return_value=("Followed", tracks)) as fetch:
            self.view._on_playlist_selected(self.view.playlist_list.item(1))
        worker_cls.assert_not_called()
        fetch.assert_called_once_with("playlist", "followed")
        self.assertEqual(self.view.tracks_table.rowCount(), 1)

    def test_download_queue_keeps_followed_playlists(self):
        self.view.playlist_list.selectAll()
        with mock.patch.object(spotify_view_module, "SpotifyWorker") as worker_cls:
            self.view._download_selected_playlists()
        worker_cls.return_value.fetch_playlist_tracks.assert_called_once_with("owned", "Owned")
        self.assertEqual(self.view._download_queue_playlists, [self.followed])

    def test_workers_share_the_view_client(self):
        with mock.patch.object(spotify_view_module, "SpotifyWorker") as worker_cls:
            self.view._on_playlist_selected(self.view.playlist_list.item(0))
        self.assertIs(worker_cls.call_args.kwargs["client"], self.view._client)

    def test_login_token_reaches_client_without_disk_cache(self):
        token = TokenInfo(access_token="AT", token_type="Bearer", expires_at=9999999999.0)
        with mock.patch.object(spotify_view_module, "SpotifyOAuthDialog") as dialog_cls, \
             mock.patch.object(spotify_view_module, "check_spotify_credentials", return_value={"ok": True}):
            self.view._show_oauth_dialog()
        dialog_cls.return_value.auth.token_manager.save({"spotify_cache_tokens": False}, token)
        with mock.patch.object(SpotifyView, "_refresh_playlists"):
            self.view._on_auth_completed(True, "ok")
        self.assertEqual(self.view._client.get_token(), token)

    def test_stop_worker_never_terminates(self):
        worker = mock.Mock()
        worker.isRunning.return_value = True
        worker.wait.return_value = False
        self.view.worker = worker
        self.view._stop_worker()
        worker.cancel.assert_called_once()
        worker.terminate.assert_not_called()
        self.assertLessEqual(worker.wait.call_args[0][0], 5000)
        self.assertIn(worker, self.view._retired_workers)

    def test_cancelled_download_fetch_reports_unqueued(self):
        worker = mock.Mock()
        worker.isRunning.return_value = True
        worker.wait.return_value = True
        self.view.worker = worker
        self.view._download_fetch_worker = worker
        self.view._download_queue_playlists = [self.owned, self.owned]
        with mock.patch.object(spotify_view_module, "notify") as notice:
            self.view._stop_worker()
        self.assertIn("3 playlist", notice.call_args[0][0])
        self.assertEqual(self.view._download_queue_playlists, [])

    def test_stop_worker_twice_waits_and_retires_once(self):
        worker = mock.Mock()
        worker.isRunning.return_value = True
        worker.wait.return_value = False
        self.view.worker = worker
        self.view._stop_worker()
        self.view._stop_worker()
        self.assertEqual(worker.wait.call_count, 1)
        self.assertEqual(self.view._retired_workers.count(worker), 1)
        self.assertEqual(worker.finished.connect.call_count, 1)

    def test_error_mid_download_fetch_reports_unqueued(self):
        worker = mock.Mock()
        worker.isRunning.return_value = False
        self.view.worker = worker
        self.view._download_fetch_worker = worker
        self.view._download_queue_playlists = [self.owned, self.owned]
        with mock.patch.object(spotify_view_module.QMessageBox, "warning") as warning:
            self.view._on_error(403, "Forbidden")
        self.assertIn("2 more playlist(s) were not queued", warning.call_args[0][2])
        self.assertEqual(self.view._download_queue_playlists, [])
        self.assertIsNone(self.view._download_fetch_worker)


class TestCliListing(unittest.TestCase):
    def test_unfetchable_marked_and_skipped(self):
        client = FakeClient([_playlist("owned", ME_ID), _playlist("followed", "someone")], item_total=2)
        captured = {}

        def fake_checkbox(message, choices):
            captured["choices"] = choices
            return mock.Mock(ask=mock.Mock(return_value=["owned", "followed"]))

        with mock.patch("spotify_api.client.SpotifyClient", return_value=client), \
             mock.patch.object(downloads_menu.questionary, "checkbox", fake_checkbox), \
             mock.patch.object(downloads_menu.questionary, "text") as text, \
             mock.patch.object(downloads_menu, "select_songs_for_playlist", return_value=[]), \
             mock.patch.object(downloads_menu, "log_info"), \
             mock.patch.object(downloads_menu, "log_warning"), \
             mock.patch.object(downloads_menu, "log_error") as log_error:
            text.return_value.ask.return_value = ""
            downloads_menu._spotify_download_from_playlists({"output_dir": THIS_DIR})
        log_error.assert_not_called()
        disabled = {c.value: c.disabled for c in captured["choices"]}
        self.assertFalse(disabled["owned"])
        self.assertTrue(disabled["followed"])
        self.assertEqual({pid for pid, _ in client.item_calls}, {"owned"})
        self.assertEqual(client.me_calls, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
