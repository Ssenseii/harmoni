import ast
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(THIS_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from utils import system

SUBPROCESS_CALLS = {"run", "Popen", "check_output", "check_call", "call"}
SKIP_DIRS = {"tests", "history", "__pycache__", "venv", "build", "dist"}

CONSOLE_CLI_CALLS = {
    ("downloader/youtube_link_downloader.py", "download_from_link"),
    ("downloader/youtube_link_downloader.py", "download_from_playlist"),
}


def _enclosing_function(rel: str, lineno: int) -> str:
    """Return the name of the innermost function in a repo file that contains a line.

    @param rel: Repo-relative path of the file.
    @param lineno: Line number inside that file.
    """
    with open(os.path.join(REPO_ROOT, rel), "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=rel)
    name, best = "", 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= lineno <= node.end_lineno and node.lineno >= best:
                name, best = node.name, node.lineno
    return name


def _is_hidden_call(node: ast.Call) -> bool:
    """Return True when a subprocess call passes hidden_subprocess_kwargs or creationflags.

    @param node: The ast.Call node for the subprocess call.
    """
    for kw in node.keywords:
        if kw.arg == "creationflags":
            return True
        if kw.arg is None and isinstance(kw.value, ast.Call):
            func = kw.value.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "hidden_subprocess_kwargs":
                return True
    return False


def find_unhidden_subprocess_calls(root: str) -> list:
    """List (relative path, line) for every subprocess call that can open a console window.

    @param root: Repository root to scan.
    """
    offenders = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            with open(path, "r", encoding="utf-8") as f:
                try:
                    tree = ast.parse(f.read(), filename=rel)
                except SyntaxError:
                    continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr in SUBPROCESS_CALLS
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "subprocess"
                    and not _is_hidden_call(node)
                ):
                    offenders.append((rel, node.lineno))
    return offenders


class TestNoConsoleWindowSubprocessCalls(unittest.TestCase):
    def test_every_file_hides_console_windows(self):
        """Only the CLI link downloads may inherit the console, so yt-dlp progress stays visible."""
        offenders = find_unhidden_subprocess_calls(REPO_ROOT)
        located = sorted({(rel, _enclosing_function(rel, line)) for rel, line in offenders})
        self.assertEqual(located, sorted(CONSOLE_CLI_CALLS), f"Console-window subprocess calls: {offenders}")
        self.assertEqual(len(offenders), len(CONSOLE_CLI_CALLS))

    def test_scanner_flags_a_bare_call(self):
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "bad.py"), "w", encoding="utf-8") as f:
                f.write("import subprocess\nsubprocess.run(['x'])\n")
            with open(os.path.join(td, "good.py"), "w", encoding="utf-8") as f:
                f.write(
                    "import subprocess\n"
                    "from utils.system import hidden_subprocess_kwargs\n"
                    "subprocess.run(\n    ['x'],\n    **hidden_subprocess_kwargs(),\n)\n"
                )
            self.assertEqual(find_unhidden_subprocess_calls(td), [("bad.py", 2)])


class TestHiddenKwargsReachSubprocess(unittest.TestCase):
    def test_get_installed_version_passes_hidden_kwargs(self):
        from tools import ytdlp_update_checker

        with mock.patch.object(
            ytdlp_update_checker, "hidden_subprocess_kwargs", return_value={"creationflags": 123}
        ), mock.patch("tools.ytdlp_update_checker.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="2024.08.06\n")
            ytdlp_update_checker.get_installed_version(None)

        self.assertEqual(run.call_args.kwargs.get("creationflags"), 123)


class TestHiddenSubprocessKwargs(unittest.TestCase):
    def test_windows_returns_create_no_window(self):
        with mock.patch.object(system.sys, "platform", "win32"):
            self.assertEqual(
                system.hidden_subprocess_kwargs(),
                {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)},
            )

    def test_other_platforms_return_empty(self):
        for platform in ("linux", "darwin"):
            with mock.patch.object(system.sys, "platform", platform):
                self.assertEqual(system.hidden_subprocess_kwargs(), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
