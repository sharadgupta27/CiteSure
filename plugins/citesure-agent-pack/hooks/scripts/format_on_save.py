"""PostToolUse: format and lint the file the agent just wrote, so style never depends on "please be careful".

Python -> ruff format + ruff check --fix (backend). TypeScript -> eslint --fix (frontend).
Remaining problems are reported to the agent (exit 2) so it fixes them in the same turn. Never blocks on missing tools.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from common import ROOT, audit, read_event, rel


def run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, timeout=90)  # noqa: S603


def main() -> None:
    event = read_event()
    path = rel((event.get("tool_input") or {}).get("file_path"))
    problems = ""
    try:
        if path.startswith("backend/") and path.endswith(".py") and shutil.which("uv"):
            target = path.removeprefix("backend/")
            run(["uv", "run", "ruff", "format", target], str(ROOT / "backend"))
            result = run(["uv", "run", "ruff", "check", "--fix", target], str(ROOT / "backend"))
            if result.returncode != 0:
                problems = (result.stdout + result.stderr).strip()[-1500:]
        elif path.startswith("frontend/src/") and path.endswith((".ts", ".tsx")) and shutil.which("npx"):
            target = path.removeprefix("frontend/")
            result = run(["npx", "--no-install", "eslint", "--fix", target], str(ROOT / "frontend"))
            if result.returncode != 0:
                problems = (result.stdout + result.stderr).strip()[-1500:]
    except (OSError, subprocess.TimeoutExpired):
        pass  # formatting is a convenience; a missing tool must not stop the agent
    if problems:
        audit(event, "lint-problems", path)
        print(f"Lint problems remain in {path}; please fix them:\n{problems}", file=sys.stderr)
        sys.exit(2)
    audit(event, "formatted", path)


if __name__ == "__main__":
    main()
