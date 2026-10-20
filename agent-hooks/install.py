"""Keep the agent extension pack in sync. The canonical files live in agent-capabilities/, agent-hooks/ and mcp-server/;
Claude Code reads copies from .claude/, and the shareable plugin bundles its own copies.

    python agent-hooks/install.py          # copy canonical -> .claude/ and plugins/citesure-agent-pack/
    python agent-hooks/install.py --check  # exit 1 if any copy is missing or differs (used by tests and CI)

Copies (not symlinks) so it works on Windows and inside a plugin cache.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPS = ROOT / "agent-capabilities"
HOOKS = ROOT / "agent-hooks"
MCP = ROOT / "mcp-server"
PLUGIN = ROOT / "plugins" / "citesure-agent-pack"
SKILLS = ["add-golden-question", "ingest-new-doc-type", "tune-retrieval", "review-api-change"]
HOOK_FILES = ["common.py", "guard.py", "format_on_save.py", "stop_tests.py", "approve_golden_change.py", "check_golden_append_only.py"]
MCP_FILES = ["server.py", "citesure_client.py", "pyproject.toml"]


def pairs() -> list[tuple[Path, Path]]:
    """(canonical source, copy) for every synced file."""
    result: list[tuple[Path, Path]] = []
    for skill in SKILLS:
        source = CAPS / skill / "SKILL.md"
        result.append((source, ROOT / ".claude" / "skills" / skill / "SKILL.md"))
        result.append((source, PLUGIN / "skills" / skill / "SKILL.md"))
    for agent in sorted((CAPS / "subagents").glob("*.md")):
        result.append((agent, ROOT / ".claude" / "agents" / agent.name))
        result.append((agent, PLUGIN / "agents" / agent.name))
    for name in HOOK_FILES:
        result.append((HOOKS / name, PLUGIN / "hooks" / "scripts" / name))
    for name in MCP_FILES:
        result.append((MCP / name, PLUGIN / "mcp-server" / name))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    drift: list[str] = []
    for source, copy in pairs():
        same = copy.exists() and copy.read_bytes() == source.read_bytes()
        if args.check:
            if not same:
                drift.append(str(copy.relative_to(ROOT)))
        elif not same:
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, copy)
            print("synced", copy.relative_to(ROOT).as_posix())
    if args.check:
        for path in drift:
            print("OUT OF SYNC:", path, file=sys.stderr)
        if drift:
            print("Run: python agent-hooks/install.py", file=sys.stderr)
        return 1 if drift else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
