"""Repository hygiene checks: no personal data or secrets tracked, configs stay sane."""
import fnmatch
import os
import subprocess
import unittest

try:
    import yaml
except ImportError:
    yaml = None

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS_DIR = os.path.join(PROJECT_ROOT, ".github", "workflows")

LEAKED_CLIENT_ID = "d99b082b01d74d61" + "a100c9a0e056380b"


def _read(rel_path):
    """Read a project file as text.

    @param rel_path: Path relative to the project root.
    """
    with open(os.path.join(PROJECT_ROOT, rel_path), "r", encoding="utf-8") as f:
        return f.read()


def _tracked_files():
    """Return the repo-relative paths git tracks, or None outside a git checkout."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=PROJECT_ROOT, capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p.decode("utf-8") for p in out.split(b"\0") if p]


def _dockerignored(path, patterns):
    """Return whether .dockerignore patterns exclude a path, applying ! re-includes in order.

    @param path: Forward-slash path relative to the build context.
    @param patterns: Non-comment .dockerignore lines in file order.
    """
    ignored = False
    for pat in patterns:
        negate = pat.startswith("!")
        pat = (pat[1:] if negate else pat).rstrip("/")
        if fnmatch.fnmatch(path, pat) or path.startswith(pat + "/"):
            ignored = not negate
    return ignored


TRACKED = _tracked_files()


@unittest.skipIf(TRACKED is None, "not a git checkout")
class TestTrackedFiles(unittest.TestCase):
    def test_no_personal_data_is_tracked(self):
        offenders = [
            p for p in TRACKED
            if p.startswith("export/")
            or (fnmatch.fnmatch(p, "data/*.json") and not p.endswith(".example.json"))
        ]
        self.assertEqual(offenders, [])

    def test_no_tracked_file_contains_leaked_client_id(self):
        needle = LEAKED_CLIENT_ID.encode("ascii")
        offenders = []
        for rel in TRACKED:
            path = os.path.join(PROJECT_ROOT, rel)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    if needle in f.read():
                        offenders.append(rel)
        self.assertEqual(offenders, [])


class TestDockerIgnore(unittest.TestCase):
    def test_excludes_personal_files_but_keeps_examples(self):
        patterns = [
            ln.strip() for ln in _read(".dockerignore").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        for path in ("config.json", "data/tracks.json", "data/spotify_tokens.json", "export/a.json"):
            self.assertTrue(_dockerignored(path, patterns), path)
        for path in ("config.json.example", "data/tracks.example.json"):
            self.assertFalse(_dockerignored(path, patterns), path)


class TestWorkflows(unittest.TestCase):
    @unittest.skipIf(yaml is None, "PyYAML is not installed")
    def test_every_workflow_parses(self):
        names = [n for n in os.listdir(WORKFLOWS_DIR) if n.endswith((".yml", ".yaml"))]
        self.assertTrue(names)
        for name in names:
            with self.subTest(workflow=name):
                doc = yaml.safe_load(_read(os.path.join(".github", "workflows", name)))
                self.assertIn("jobs", doc)

    @unittest.skipIf(yaml is None, "PyYAML is not installed")
    def test_builds_need_tests_and_only_release_can_write(self):
        doc = yaml.safe_load(_read(os.path.join(".github", "workflows", "build.yml")))
        self.assertEqual(doc["permissions"], {"contents": "read"})
        for job in ("build-windows", "build-macos", "build-linux"):
            self.assertEqual(set(doc["jobs"][job]["needs"]), {"test", "check-version"}, job)
        writers = [n for n, j in doc["jobs"].items() if j.get("permissions", {}).get("contents") == "write"]
        self.assertEqual(writers, ["release"])

    def test_builds_do_not_bundle_data_folder(self):
        for rel in (os.path.join(".github", "workflows", "build.yml"), "build-macos.sh"):
            self.assertNotRegex(_read(rel), r"--add-data\s+\"data[;:]data\"", rel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
