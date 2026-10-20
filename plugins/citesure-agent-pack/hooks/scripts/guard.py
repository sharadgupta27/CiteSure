"""PreToolUse guardrail. Blocks, with a reason the agent can act on:

1. Reading or writing secrets: `.env*` files (except `.env.example`).
2. Reading raw corpus documents (`corpus/raw/`): they may be licensed or private.
3. Editing the golden evaluation set without a fresh, reasoned approval (guards against "fixing" the eval so a
   regression passes). Use the add-golden-question skill, which records the approval.
4. Editing committed Alembic migrations (create a new one) and the generated TypeScript client.
5. Editing the guardrails themselves (agent-hooks, .claude/settings.json) without CITESURE_HOOKS_UNLOCK=1.
6. Destructive or outward-facing shell commands: rm -rf, force push, reset --hard, dropping volumes/tables,
   anything on AWS, deploy commands; and shell tricks that write the golden set or read secrets.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from common import APPROVAL_TTL_SECONDS, GOLDEN_APPROVAL, audit, block, git, head_sha, read_event, rel

FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Read"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
GOLDEN_IN_COMMAND = r"backend/evals/golden[\w.\-]*\.jsonl"

DANGEROUS_COMMANDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b"), "rm -rf"),
    (re.compile(r"\bgit\s+push\b.*(--force\b|\s-f\b|--force-with-lease)"), "git force push"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git reset --hard"),
    (re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"), "git clean -f"),
    (re.compile(r"\bdocker\s+volume\s+(rm|prune)\b"), "deleting Docker volumes"),
    (re.compile(r"\bdocker\s+compose\b.*\bdown\b.*(-v\b|--volumes\b)"), "compose down -v (deletes the database)"),
    (re.compile(r"\bdrop\s+(table|database|schema)\b", re.I), "dropping database objects"),
    (re.compile(r"\btruncate\s+table\b", re.I), "truncating tables"),
    (re.compile(r"\baws\s"), "AWS CLI commands (no cloud actions without explicit approval)"),
    (re.compile(r"\b(terraform|pulumi)\s+(apply|destroy|up)\b"), "infrastructure changes"),
    (re.compile(r"\bgh\s+workflow\s+run\b.*deploy", re.I), "triggering a deployment"),
    (re.compile(r"\bdocker\s+push\b"), "pushing images (deployment is a human decision)"),
    (re.compile(r"\b(cat|type|more|less|head|tail|Get-Content|grep|rg)\b[^|;&]*\.env(?!\.example)\b"), "reading .env secrets"),
    (re.compile(r"\b(cat|type|less|head|tail|Get-Content|grep|rg|ls|find)\b[^|;&]*corpus/raw"), "reading raw corpus documents"),
    # Writing the golden set through the shell would sidestep the file-tool check above.
    (re.compile(rf"(>|>>|\btee\b|\bsed\s+-i|\bmv\b|\bcp\b|\brm\b|\btruncate\b)[^|;&]*{GOLDEN_IN_COMMAND}"), "writing the golden set from the shell"),
    (re.compile(rf"\bgit\s+(checkout|restore|reset)\b[^|;&]*{GOLDEN_IN_COMMAND}"), "rewriting the golden set through git"),
]


def norm(path: str) -> str:
    """Forward slashes and no trailing noise. All rules below match the TAIL of the path (at any depth), so they still
    fire if the project root cannot be made relative (Git Bash /d/... paths, symlinks, a different drive spelling).
    A guardrail that fails open on an unusual path is worse than none."""
    return path.replace("\\", "/")


def tail(path: str, pattern: str) -> bool:
    return re.search(rf"(^|/){pattern}$", norm(path), re.IGNORECASE) is not None


def is_secret_file(path: str) -> bool:
    name = norm(path).rsplit("/", 1)[-1]
    return name.lower().startswith(".env") and name.lower() != ".env.example"


def project_relative(path: str) -> str:
    """The part of the path from the first known top-level folder, for git lookups."""
    match = re.search(r"(?:^|/)((?:backend|frontend|corpus|agent-hooks|\.claude)/.*)$", norm(path), re.IGNORECASE)
    return match.group(1) if match else norm(path)


def is_committed_migration(path: str) -> bool:
    if not tail(path, r"backend/migrations/versions/[^/]+\.py"):
        return False
    return git("ls-files", "--error-unmatch", project_relative(path)).returncode == 0


def golden_approved() -> tuple[bool, str]:
    if not GOLDEN_APPROVAL.exists():
        return False, "no approval recorded"
    try:
        data: dict[str, Any] = json.loads(GOLDEN_APPROVAL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "approval file unreadable"
    if time.time() - float(data.get("approved_at", 0)) > APPROVAL_TTL_SECONDS:
        return False, "approval expired (older than 2 hours)"
    if data.get("head") != head_sha():
        return False, "approval was for a previous commit"
    if len(str(data.get("reason", "")).strip()) < 10:
        return False, "approval has no real reason"
    return True, str(data.get("reason", ""))


def check_file(event: dict[str, Any], tool: str, path: str) -> None:
    if is_secret_file(path):
        block(event, f"{path} may contain secrets. Document variables in .env.example instead.")
    if re.search(r"(^|/)corpus/raw(/|$)", norm(path), re.IGNORECASE):
        block(event, "corpus/raw/ holds downloaded third-party documents (possibly licensed or private). Do not read or edit it.")
    if tool not in WRITE_TOOLS:
        return
    if tail(path, r"backend/evals/golden[^/]*\.jsonl"):
        ok, why = golden_approved()
        if not ok:
            block(
                event,
                f"{path} is the golden evaluation set ({why}). Never edit it to make metrics pass. "
                "Follow the add-golden-question skill: it proves the new question fails today, records the reason with "
                '`python agent-hooks/approve_golden_change.py "<reason>"`, and only APPENDS entries.',
            )
    if is_committed_migration(path):
        block(event, f"{path} is a committed migration and may already be applied. Create a new one: cd backend && uv run alembic revision --autogenerate -m '<msg>'")
    if tail(path, r"frontend/src/api/schema\.d\.ts"):
        block(event, "schema.d.ts is generated. Edit openapi.yaml, then run: cd frontend && npm run gen:api")
    guardrail = tail(path, r"agent-hooks/[^/]+\.py") or tail(path, r"\.claude/settings(\.local)?\.json")
    if guardrail and os.environ.get("CITESURE_HOOKS_UNLOCK") != "1":
        block(event, f"{path} is part of the guardrails. An agent must not loosen its own guardrails; ask the user (they can set CITESURE_HOOKS_UNLOCK=1).")


def main() -> None:
    event = read_event()
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    if tool in FILE_TOOLS:
        check_file(event, tool, rel(tool_input.get("file_path") or tool_input.get("notebook_path")))
    elif tool == "Bash":
        command = tool_input.get("command", "")
        for pattern, label in DANGEROUS_COMMANDS:
            if pattern.search(command):
                block(event, f"{label} is not allowed without explicit human approval. Ask the user.")
    audit(event, "allow")


if __name__ == "__main__":
    main()
