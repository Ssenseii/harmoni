"""Guard against the app breaking in the packaged build.

HARMONI.spec excludes a long list of PySide6 submodules (QtWebEngine, QtQml,
QtMultimedia, QtSvg, QtSql, ...) to keep the frozen exe small. If any source
file ever imports one of those excluded submodules, the app would still run
from source but crash at import time in the PyInstaller-built exe.

This test parses the exclude list directly out of HARMONI.spec (so it can't
drift out of sync) and verifies:
  1. No .py file under the project imports an excluded submodule.
  2. Every project module still imports successfully with those submodules
     replaced by a simulated ImportError, i.e. as if PyInstaller had actually
     left them out of the build.
"""
import ast
import builtins
import importlib
import os
import re
import sys
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(THIS_DIR)
SPEC_PATH = os.path.join(PROJECT_ROOT, "HARMONI.spec")
BUILD_WORKFLOW_PATH = os.path.join(PROJECT_ROOT, ".github", "workflows", "build.yml")

# Directories we don't ship / don't need to validate.
SKIP_DIR_PARTS = {".git", "__pycache__", "node_modules", "venv", ".venv", "build", "dist", "site", "_site"}  # site/ is the website build script, not app code (and shadows stdlib `site`)


def _load_excluded_modules():
    with open(SPEC_PATH, "r", encoding="utf-8") as f:
        spec_src = f.read()

    match = re.search(r"excludes\s*=\s*\[(.*?)\]", spec_src, re.DOTALL)
    assert match, "Could not find excludes=[...] in HARMONI.spec"

    # The excludes list is a plain list of string literals; parse it safely.
    excluded = ast.literal_eval("[" + match.group(1) + "]")
    assert excluded, "HARMONI.spec excludes list is empty; nothing to guard against"
    return excluded


def _load_workflow_exclude_lists():
    """Return each PySide6 exclude list in build.yml, keyed by "windows" or "bash-<index>"."""
    with open(BUILD_WORKFLOW_PATH, "r", encoding="utf-8") as f:
        src = f.read()

    lists = {}
    pwsh = re.search(r"\$qtUnused\s*=\s*@\((.*?)\)", src, re.DOTALL)
    assert pwsh, "Could not find $qtUnused = @(...) in build.yml"
    lists["windows"] = {"PySide6." + m for m in re.findall(r"'([^']+)'", pwsh.group(1))}

    for i, names in enumerate(re.findall(r'QT_UNUSED="([^"]*)"', src)):
        lists[f"bash-{i}"] = {"PySide6." + m for m in names.split()}
    return lists


def _iter_project_py_files():
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIR_PARTS]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def _iter_project_modules():
    for path in _iter_project_py_files():
        rel = os.path.relpath(path, PROJECT_ROOT)
        if rel.startswith("tests" + os.sep) or rel.startswith("history" + os.sep):
            continue
        parts = rel[:-3].split(os.sep)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        yield ".".join(parts)


class TestNoSourceImportsExcludedPySide6Modules(unittest.TestCase):
    def test_excludes_list_is_not_empty(self):
        self.assertGreater(len(_load_excluded_modules()), 10)

    def test_build_workflow_exclude_lists_match_spec(self):
        spec = set(_load_excluded_modules())
        lists = _load_workflow_exclude_lists()
        self.assertEqual(sorted(lists), ["bash-0", "bash-1", "windows"])
        for name, modules in lists.items():
            self.assertEqual(modules, spec, f"build.yml {name} exclude list differs from HARMONI.spec")

    def test_no_file_imports_an_excluded_submodule(self):
        excluded = set(_load_excluded_modules())
        offenders = []

        for path in _iter_project_py_files():
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue

            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()

            for name in excluded:
                # Match "import PySide6.QtSvg" / "from PySide6.QtSvg import ..."
                pattern = r"\b(?:import|from)\s+" + re.escape(name) + r"\b"
                if re.search(pattern, source):
                    offenders.append((os.path.relpath(path, PROJECT_ROOT), name))

        self.assertEqual(offenders, [], f"Found imports of excluded PySide6 modules: {offenders}")


class TestAppImportsWithoutExcludedModules(unittest.TestCase):
    """Simulates a PyInstaller build where the excluded submodules are absent,
    by making them raise ImportError, then imports every project module."""

    def test_every_module_imports_with_excluded_submodules_missing(self):
        excluded = _load_excluded_modules()
        real_dunder_import = builtins.__import__

        def blocked_dunder_import(name, *args, **kwargs):
            if name in excluded or any(name.startswith(e + ".") for e in excluded):
                raise ImportError(f"simulated PyInstaller exclusion: {name}")
            return real_dunder_import(name, *args, **kwargs)

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        module_names = sorted(set(_iter_project_modules()))
        # Drop cached copies so imports actually re-execute under the blocked
        # __import__, instead of returning an already-imported module untouched.
        prior_modules = {
            name: mod for name, mod in sys.modules.items()
            if name in module_names or any(name.startswith(m + ".") for m in module_names)
        }
        for name in list(prior_modules):
            del sys.modules[name]

        failed = []
        builtins.__import__ = blocked_dunder_import
        try:
            for mod_name in module_names:
                try:
                    importlib.import_module(mod_name)
                except Exception as e:  # noqa: BLE001 - we want to report *any* break
                    failed.append((mod_name, repr(e)))
        finally:
            builtins.__import__ = real_dunder_import
            # Restore prior module cache so we don't leak the blocked-state
            # imports (or their absence) into other tests in the same run.
            for name in list(sys.modules):
                if name in module_names or any(name.startswith(m + ".") for m in module_names):
                    del sys.modules[name]
            sys.modules.update(prior_modules)

        self.assertEqual(failed, [], f"Modules failed to import without excluded PySide6 submodules: {failed}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
