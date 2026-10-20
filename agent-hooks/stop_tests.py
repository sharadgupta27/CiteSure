"""Stop hook: before the agent declares it is done, run the fast checks that protect the non-negotiables.

1. golden set: quotes still exist in the corpus, and the set is append-only,
2. backend unit tests (fake providers, no Docker, ~10 s) which include the ACL rule tests,
3. if the frontend changed: typecheck and unit tests.

If anything fails the agent is told (exit 2) and must fix it. `stop_hook_active` prevents an endless loop:
the second time around the hook lets the agent stop and reports the failure to the human instead.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from common import ROOT, audit, git, read_event


def run(cmd: list[str], cwd: str, timeout: int = 240) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not run {' '.join(cmd)}: {exc}"
    return result.returncode == 0, (result.stdout + result.stderr).strip()[-1200:]


def frontend_changed() -> bool:
    changed = git("status", "--porcelain", "--", "frontend/src", "openapi.yaml").stdout.strip()
    return bool(changed)


def main() -> None:
    event = read_event()
    failures: list[str] = []
    python = sys.executable

    ok, out = run([python, "corpus/validate_golden.py"], str(ROOT))
    if not ok:
        failures.append(f"golden set no longer matches the corpus:\n{out}")
    ok, out = run([python, "agent-hooks/check_golden_append_only.py"], str(ROOT))
    if not ok:
        failures.append(f"golden set was weakened:\n{out}")

    if shutil.which("uv"):
        ok, out = run(["uv", "run", "pytest", "-m", "not integration", "-q", "-x", "--no-header"], str(ROOT / "backend"))
        if not ok:
            failures.append(f"backend unit tests (including the ACL rules) fail:\n{out}")
    if shutil.which("npm") and frontend_changed():
        ok, out = run(["npm", "run", "typecheck", "--silent"], str(ROOT / "frontend"))
        if ok:
            ok, out = run(["npm", "run", "test", "--silent"], str(ROOT / "frontend"))
        if not ok:
            failures.append(f"frontend typecheck/tests fail:\n{out}")

    if not failures:
        audit(event, "stop-ok")
        return
    audit(event, "stop-failed", f"{len(failures)} check(s)")
    message = "Do not finish yet. Fix these first (do not weaken or delete tests to make them pass):\n\n" + "\n\n".join(failures)
    if event.get("stop_hook_active"):
        print(message + "\n\n(Second attempt: stopping anyway; the human must review this.)", file=sys.stderr)
        return
    print(message, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
