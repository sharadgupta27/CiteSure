"""Download a slice of the GitLab Handbook (CC BY-SA 4.0) into corpus/raw/ for a bigger demo.

The pages are not committed to git. Usage:
    uv run --no-project --with httpx python corpus/fetch_gitlab_handbook.py --limit 200
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

API = "https://gitlab.com/api/v4/projects/{project}/repository"
PROJECT = quote("gitlab-com/content-sites/handbook", safe="")
RAW_DIR = Path(__file__).resolve().parent / "raw" / "gitlab-handbook"
START_PATH = "content/handbook/people-group"


def list_markdown_files(client: httpx.Client, limit: int) -> list[str]:
    paths: list[str] = []
    page = 1
    while len(paths) < limit:
        resp = client.get(
            API.format(project=PROJECT) + "/tree",
            params={"path": START_PATH, "recursive": "true", "per_page": 100, "page": page},
        )
        resp.raise_for_status()
        items = resp.json()
        if not items:
            break
        paths += [i["path"] for i in items if i["type"] == "blob" and i["path"].endswith(".md")]
        page += 1
    return paths[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        paths = list_markdown_files(client, args.limit)
        for i, path in enumerate(paths, 1):
            raw = client.get(
                API.format(project=PROJECT) + f"/files/{quote(path, safe='')}/raw", params={"ref": "main"}
            )
            if raw.status_code != 200:
                print(f"skip {path}: HTTP {raw.status_code}", file=sys.stderr)
                continue
            target = RAW_DIR / path.removeprefix("content/").replace("/", "__")
            target.write_text(raw.text, encoding="utf-8")
            print(f"[{i}/{len(paths)}] {target.name}")
    print(f"Saved to {RAW_DIR}. Source: GitLab Handbook, CC BY-SA 4.0 (attribution required).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
