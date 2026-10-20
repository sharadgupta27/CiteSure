"""Pin every GitHub Action in .github/workflows to a full commit SHA (supply-chain hardening).

A tag such as `actions/checkout@v4` can be silently repointed by whoever owns the action. A commit SHA cannot.
The original tag is kept as a comment so humans (and Dependabot) can still read and update it.

    python security/pin_actions.py          # rewrite the workflow files
    python security/pin_actions.py --check  # exit 1 if any action is still unpinned (used in CI)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
USES = re.compile(r"^(?P<indent>\s*(?:-\s+)?uses:\s*)(?P<repo>[\w.-]+/[\w.-]+)@(?P<ref>[^\s#]+)(?P<rest>.*)$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def resolve(repo: str, ref: str) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", "ls-remote", f"https://github.com/{repo}.git", f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.strip().splitlines()
    peeled = [line.split()[0] for line in out if line.endswith("^{}")]  # annotated tags point at a tag object
    plain = [line.split()[0] for line in out if not line.endswith("^{}")]
    sha = (peeled or plain or [""])[0]
    if not SHA.match(sha):
        raise SystemExit(f"could not resolve {repo}@{ref}")
    return sha


def main() -> int:
    check = "--check" in sys.argv
    unpinned: list[str] = []
    cache: dict[tuple[str, str], str] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        changed = False
        for i, line in enumerate(lines):
            match = USES.match(line)
            if not match or SHA.match(match["ref"]) or match["repo"].startswith("./"):
                continue
            unpinned.append(f"{path.name}: {match['repo']}@{match['ref']}")
            if check:
                continue
            key = (match["repo"], match["ref"])
            cache.setdefault(key, resolve(*key))
            lines[i] = f"{match['indent']}{match['repo']}@{cache[key]} # {match['ref']}"
            changed = True
        if changed:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for item in unpinned:
        print(("UNPINNED " if check else "pinned   ") + item)
    return 1 if (check and unpinned) else 0


if __name__ == "__main__":
    sys.exit(main())
