"""Tests that the MusicBrainz rate limit holds when several download threads tag files at once."""
import os
import sys
import threading
import time
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)
    sys.path.insert(0, os.path.dirname(THIS_DIR))

from downloader import metadata


class TestMusicBrainzRateLimit(unittest.TestCase):
    def test_parallel_callers_are_spaced_by_the_rate_limit(self):
        spacing = 0.1
        stamps = []
        stamps_lock = threading.Lock()

        def call():
            metadata._wait_for_mb_slot()
            with stamps_lock:
                stamps.append(time.monotonic())

        with mock.patch.object(metadata, "MB_RATE_LIMIT_SECONDS", spacing), \
             mock.patch.object(metadata, "_last_mb_request_at", 0.0):
            threads = [threading.Thread(target=call) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(5)

        stamps.sort()
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        self.assertEqual(len(stamps), 4)
        self.assertTrue(all(gap >= spacing * 0.9 for gap in gaps), gaps)


if __name__ == "__main__":
    unittest.main()
