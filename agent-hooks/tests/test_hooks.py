"""Tests for the guardrail hooks. Each test runs the real hook script as a subprocess, with the same JSON-on-stdin
protocol Claude Code uses, inside a throw-away project directory (so no real golden set or repository is touched).

    python -m pytest agent-hooks/tests -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent
REPO = HOOKS.parent
sys.path.insert(0, str(HOOKS))

import check_golden_append_only as golden_check  # noqa: E402


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A fake project root with a git repository, so `git rev-parse HEAD` and `git ls-files` behave."""
    (tmp_path / "backend" / "evals").mkdir(parents=True)
    (tmp_path / "backend" / "migrations" / "versions").mkdir(parents=True)
    (tmp_path / "backend" / "evals" / "golden.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "backend" / "migrations" / "versions" / "0001_init.py").write_text("# applied\n", encoding="utf-8")
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("add", ".")
    # Throw-away repository: never sign (a global commit.gpgsign=true would otherwise wait for a passphrase and hang the suite).
    run("-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-qm", "init")
    return tmp_path


def run_hook(script: str, project: Path, event: dict, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), **(env or {})}
    full_env.pop("CITESURE_HOOKS_UNLOCK", None) if env is None or "CITESURE_HOOKS_UNLOCK" not in env else None
    return subprocess.run(
        [sys.executable, str(HOOKS / script)], input=json.dumps(event), capture_output=True, text=True, env=full_env, check=False, timeout=60
    )


def tool(name: str, **tool_input: str) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input, "session_id": "test"}


def blocked(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode == 2 and "BLOCKED" in result.stderr


# --- secrets and raw data ------------------------------------------------------------------------
@pytest.mark.parametrize("path", [".env", ".env.local", "backend/.env.production"])
def test_secret_files_cannot_be_read_or_written(project: Path, path: str) -> None:
    for name in ("Read", "Edit", "Write"):
        assert blocked(run_hook("guard.py", project, tool(name, file_path=str(project / path))))


def test_env_example_is_allowed(project: Path) -> None:
    assert run_hook("guard.py", project, tool("Write", file_path=str(project / ".env.example"))).returncode == 0


@pytest.mark.parametrize("command", ["cat .env", "type backend\\.env", "Get-Content .env.production", "grep KEY .env"])
def test_shell_reads_of_secrets_are_blocked(project: Path, command: str) -> None:
    assert blocked(run_hook("guard.py", project, tool("Bash", command=command)))


def test_raw_corpus_is_off_limits(project: Path) -> None:
    assert blocked(run_hook("guard.py", project, tool("Read", file_path=str(project / "corpus" / "raw" / "handbook" / "a.md"))))
    assert blocked(run_hook("guard.py", project, tool("Bash", command="cat corpus/raw/handbook/a.md")))


# --- the golden set -----------------------------------------------------------------------------
def test_editing_the_golden_set_is_blocked_without_approval(project: Path) -> None:
    golden = str(project / "backend" / "evals" / "golden.jsonl")
    for name in ("Edit", "Write", "MultiEdit"):
        result = run_hook("guard.py", project, tool(name, file_path=golden))
        assert blocked(result)
        assert "add-golden-question" in result.stderr  # the message tells the agent the sanctioned path


@pytest.mark.parametrize(
    "path",
    [
        "/d/Some/Other/Root/backend/evals/golden.jsonl",  # Git Bash style path that is not under the project root
        r"C:\elsewhere\CiteSure\backend\evals\golden.jsonl",
        r"D:\X\BACKEND\EVALS\GOLDEN.JSONL",  # Windows paths are case-insensitive
        "backend/evals/golden-extra.jsonl",
    ],
)
def test_the_guard_fails_closed_on_unusual_path_spellings(project: Path, path: str) -> None:
    assert blocked(run_hook("guard.py", project, tool("Edit", file_path=path)))
    assert blocked(run_hook("guard.py", project, tool("Write", file_path=path)))


def test_reading_the_golden_set_is_fine(project: Path) -> None:
    assert run_hook("guard.py", project, tool("Read", file_path=str(project / "backend" / "evals" / "golden.jsonl"))).returncode == 0


@pytest.mark.parametrize(
    "command",
    [
        "echo '{}' >> backend/evals/golden.jsonl",
        "sed -i 's/16/8/' backend/evals/golden.jsonl",
        "tee backend/evals/golden.jsonl < new.jsonl",
        "cp new.jsonl backend/evals/golden.jsonl",
        "git checkout HEAD -- backend/evals/golden.jsonl",
        "rm backend/evals/golden.jsonl",
    ],
)
def test_the_shell_cannot_be_used_to_sidestep_the_golden_guard(project: Path, command: str) -> None:
    assert blocked(run_hook("guard.py", project, tool("Bash", command=command)))


def test_approval_script_requires_a_real_reason(project: Path) -> None:
    env = {"CLAUDE_PROJECT_DIR": str(project)}
    short = subprocess.run([sys.executable, str(HOOKS / "approve_golden_change.py"), "ok"], capture_output=True, text=True, env={**os.environ, **env}, check=False)
    assert short.returncode == 1 and not (project / ".claude" / "state" / "golden-approval.json").exists()


def test_a_reasoned_approval_unlocks_the_golden_set_for_the_current_commit(project: Path) -> None:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    subprocess.run([sys.executable, str(HOOKS / "approve_golden_change.py"), "Users reported the sabbatical policy is missing"], env=env, check=True, capture_output=True)
    golden = str(project / "backend" / "evals" / "golden.jsonl")
    assert run_hook("guard.py", project, tool("Edit", file_path=golden)).returncode == 0

    approval = project / ".claude" / "state" / "golden-approval.json"
    data = json.loads(approval.read_text())
    approval.write_text(json.dumps({**data, "approved_at": time.time() - 3 * 3600}))
    assert blocked(run_hook("guard.py", project, tool("Edit", file_path=golden)))  # expired

    approval.write_text(json.dumps({**data, "head": "some-other-commit"}))
    assert blocked(run_hook("guard.py", project, tool("Edit", file_path=golden)))  # a different commit


# --- other protected files ---------------------------------------------------------------------
def test_committed_migrations_are_immutable_but_new_ones_are_fine(project: Path) -> None:
    assert blocked(run_hook("guard.py", project, tool("Edit", file_path=str(project / "backend/migrations/versions/0001_init.py"))))
    assert run_hook("guard.py", project, tool("Write", file_path=str(project / "backend/migrations/versions/0002_new.py"))).returncode == 0


def test_the_generated_client_cannot_be_hand_edited(project: Path) -> None:
    result = run_hook("guard.py", project, tool("Edit", file_path=str(project / "frontend/src/api/schema.d.ts")))
    assert blocked(result) and "npm run gen:api" in result.stderr


def test_an_agent_cannot_loosen_its_own_guardrails(project: Path) -> None:
    for path in ("agent-hooks/guard.py", ".claude/settings.json"):
        assert blocked(run_hook("guard.py", project, tool("Edit", file_path=str(project / path))))
    assert run_hook("guard.py", project, tool("Edit", file_path=str(project / path)), env={"CITESURE_HOOKS_UNLOCK": "1"}).returncode == 0
    assert run_hook("guard.py", project, tool("Edit", file_path=str(project / "agent-hooks/tests/test_new.py"))).returncode == 0


# --- destructive commands ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -fr node_modules",
        "git push --force origin main",
        "git push origin main -f",
        "git reset --hard HEAD~3",
        "git clean -fd",
        "docker volume rm citesure_pgdata",
        "docker compose down -v",
        "psql -c 'DROP TABLE chunks'",
        "aws s3 rm s3://bucket --recursive",
        "terraform apply -auto-approve",
        "docker push ghcr.io/x/y",
        "gh workflow run deploy.yml",
    ],
)
def test_dangerous_commands_are_blocked(project: Path, command: str) -> None:
    assert blocked(run_hook("guard.py", project, tool("Bash", command=command)))


@pytest.mark.parametrize(
    "command",
    ["uv run pytest -q", "git status", "git diff --stat", "docker compose ps", "npm run test", "python corpus/validate_golden.py", "ls backend"],
)
def test_normal_commands_pass(project: Path, command: str) -> None:
    assert run_hook("guard.py", project, tool("Bash", command=command)).returncode == 0


def test_every_decision_is_audited_without_file_contents(project: Path) -> None:
    run_hook("guard.py", project, tool("Bash", command="git status"))
    run_hook("guard.py", project, tool("Bash", command="rm -rf /"))
    lines = [json.loads(line) for line in (project / "agent-hooks" / "logs" / "audit.jsonl").read_text().splitlines()]
    assert [entry["decision"] for entry in lines] == ["allow", "block"]
    assert all(set(entry) == {"ts", "event", "tool", "target", "decision", "reason", "session"} for entry in lines)


def test_garbage_input_does_not_crash_the_hook(project: Path) -> None:
    result = subprocess.run([sys.executable, str(HOOKS / "guard.py")], input="not json", capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)}, check=False)
    assert result.returncode == 0


# --- the golden set is append-only ---------------------------------------------------------------
BASE = json.dumps({"id": "g01", "question": "How many weeks?", "expected_answer": "16", "expected_quotes": [{"document": "a.md", "quote": "16 weeks"}], "answerable": True, "ask_as": None, "tags": [], "reason": "seed"})


def line(**changes: object) -> str:
    return json.dumps({**json.loads(BASE), **changes})


def test_appending_a_question_with_a_reason_is_fine() -> None:
    assert golden_check.check(BASE, BASE + "\n" + line(id="g02", reason="new coverage")) == []


@pytest.mark.parametrize(
    ("current", "fragment"),
    [
        ("", "deleted"),
        (line(expected_answer="8"), "'expected_answer' changed without a new reason"),
        (line(answerable=False), "'answerable' changed without a new reason"),
        (line(expected_quotes=[]), "'expected_quotes' changed without a new reason"),
        (line(question="Easier question?"), "'question' changed without a new reason"),
        (BASE + "\n" + line(id="g02", reason=""), "needs a reason"),
    ],
)
def test_weakening_the_golden_set_is_detected(current: str, fragment: str) -> None:
    problems = golden_check.check(BASE, current)
    assert any(fragment in p for p in problems), problems


def test_a_deliberate_correction_with_a_new_reason_is_flagged_for_human_review_not_silently_accepted() -> None:
    problems = golden_check.check(BASE, line(expected_answer="8", reason="Policy changed in 2026"))
    assert problems and "needs human review" in problems[0]


def test_the_real_golden_set_passes_its_own_checks() -> None:
    assert golden_check.check(None, (REPO / "backend/evals/golden.jsonl").read_text(encoding="utf-8")) == []


# --- the pack stays in sync --------------------------------------------------------------------
def test_plugin_and_claude_copies_match_the_canonical_files() -> None:
    result = subprocess.run([sys.executable, str(HOOKS / "install.py"), "--check"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_every_skill_and_subagent_has_valid_frontmatter() -> None:
    for path in [*(REPO / "agent-capabilities").glob("*/SKILL.md"), *(REPO / "agent-capabilities/subagents").glob("*.md")]:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n"), path
        header = text.split("---", 2)[1]
        assert "name:" in header and "description:" in header, path
        assert len(header.split("description:", 1)[1].strip()) > 40, f"{path} needs a description that says when to use it"


def test_read_only_subagents_have_no_write_tools() -> None:
    for name in ("retrieval-debugger", "citation-auditor", "api-contract-reviewer"):
        header = (REPO / "agent-capabilities/subagents" / f"{name}.md").read_text(encoding="utf-8").split("---", 2)[1]
        tools = next(line for line in header.splitlines() if line.startswith("tools:"))
        assert not any(word in tools for word in ("Edit", "Write", "MultiEdit", "NotebookEdit", "run_eval")), (name, tools)
