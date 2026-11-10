"""Build the static download site into ./_site (stdlib only).

    python site/build.py            # build, fetch releases.json from GitHub
    python -m http.server -d _site  # preview at http://localhost:8000

What it does:
  1. copies site/* (minus this script) to _site/
  2. copies docs/guides/*.md  -> _site/docs/   (rendered in-browser by docs.js)
  3. copies images/*.png      -> _site/images/
  4. snapshots GitHub releases -> _site/releases.json (so visitors never hit the API rate limit)

Set GITHUB_TOKEN to raise the API limit in CI. If the fetch fails the site still
builds; app.js falls back to the live API.
"""
import json
import os
import shutil
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "Ssenseii/harmoni")
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site"
OUT = ROOT / "_site"


def fetch_list(endpoint):
    items, page = [], 1
    while True:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/{endpoint}?per_page=100&page={page}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "site-build"},
        )
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            batch = json.load(resp)
        items += batch
        if len(batch) < 100:
            return items
        page += 1


def fetch_releases():
    return fetch_list("releases")


def slim(r):
    return {
        "tag_name": r["tag_name"],
        "published_at": r.get("published_at"),
        "created_at": r.get("created_at"),
        "html_url": r["html_url"],
        "prerelease": r["prerelease"],
        "draft": r["draft"],
        "assets": [
            {"name": a["name"], "size": a["size"], "browser_download_url": a["browser_download_url"]}
            for a in r.get("assets", [])
        ],
    }


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(SRC, OUT, ignore=shutil.ignore_patterns("build.py", "__pycache__"))

    (OUT / "docs").mkdir()
    for md in (ROOT / "docs" / "guides").glob("*.md"):
        shutil.copy(md, OUT / "docs" / md.name)

    (OUT / "images").mkdir()
    for img in (ROOT / "images").glob("*.png"):
        shutil.copy(img, OUT / "images" / img.name)

    try:
        data = {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "releases": [slim(r) for r in fetch_releases() if not r["draft"]],
        }
        (OUT / "releases.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        print(f"releases.json: {len(data['releases'])} releases")
    except Exception as exc:  # site still works via the live-API fallback
        print(f"warning: could not snapshot releases ({exc}); site will use the live API", file=sys.stderr)

    (OUT / ".nojekyll").touch()
    print(f"built {OUT}")


if __name__ == "__main__":
    main()
