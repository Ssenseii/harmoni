"""Tests for utils.jsonio atomic writes and corrupt-file handling."""
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in os.sys.path:
    os.sys.path.insert(0, THIS_DIR)
    os.sys.path.insert(0, os.path.dirname(THIS_DIR))

from utils import jsonio
from utils.jsonio import load_json, write_json_atomic


class TestWriteJsonAtomic(unittest.TestCase):
    def test_replaces_content_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "state.json")
            write_json_atomic(path, {"a": 1})
            write_json_atomic(path, {"b": 2})
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"b": 2})
            self.assertEqual(os.listdir(td), ["state.json"])

    def test_creates_parent_dirs_and_writes_utf8(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "nested", "deeper", "x.json")
            write_json_atomic(path, {"artist": "Björk"})
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"artist": "Björk"})

    def test_failed_dump_keeps_old_file_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "state.json")
            write_json_atomic(path, {"keep": True})
            with self.assertRaises(TypeError):
                write_json_atomic(path, {"bad": object()})
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"keep": True})
            self.assertEqual(os.listdir(td), ["state.json"])

    def test_uses_fsync_and_replace(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "state.json")
            with mock.patch.object(jsonio.os, "fsync", wraps=os.fsync) as fsync, \
                    mock.patch.object(jsonio.os, "replace", wraps=os.replace) as replace:
                write_json_atomic(path, [1, 2])
            fsync.assert_called_once()
            replace.assert_called_once()
            self.assertEqual(replace.call_args[0][1], os.path.abspath(path))

    @unittest.skipUnless(os.name == "posix", "file modes only apply on POSIX")
    def test_mode_0o600_on_posix(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "tokens.json")
            write_json_atomic(path, {"t": "x"}, mode=0o600)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


class TestLoadJson(unittest.TestCase):
    def test_missing_file_returns_default(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(load_json(os.path.join(td, "nope.json"), {"d": 1}), {"d": 1})

    def test_empty_file_returns_default(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "empty.json")
            open(path, "w").close()
            self.assertEqual(load_json(path, []), [])
            self.assertTrue(os.path.exists(path))

    def test_valid_file_is_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "ok.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"x": [1]}, f)
            self.assertEqual(load_json(path, None), {"x": [1]})

    def test_corrupt_file_is_renamed_and_default_returned(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bad.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not json")
            with mock.patch.object(jsonio, "log_warning") as warn:
                self.assertEqual(load_json(path, {"d": 1}), {"d": 1})
            warn.assert_called_once()
            self.assertFalse(os.path.exists(path))
            with open(path + ".corrupt", encoding="utf-8") as f:
                self.assertEqual(f.read(), "{not json")

    def test_corrupt_rename_adds_numeric_suffix_when_taken(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bad.json")
            with open(path + ".corrupt", "w", encoding="utf-8") as f:
                f.write("older")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[1,")
            with mock.patch.object(jsonio, "log_warning"):
                self.assertIsNone(load_json(path, None))
            with open(path + ".corrupt", encoding="utf-8") as f:
                self.assertEqual(f.read(), "older")
            with open(path + ".corrupt.1", encoding="utf-8") as f:
                self.assertEqual(f.read(), "[1,")


if __name__ == "__main__":
    unittest.main()
