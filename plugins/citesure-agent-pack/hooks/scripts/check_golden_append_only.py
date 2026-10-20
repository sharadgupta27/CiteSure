"""The golden set is append-only. Fails if an existing question was deleted, weakened or rewritten without a new reason.

    python agent-hooks/check_golden_append_only.py [--base HEAD]

For every question id that exists in the base commit it must still exist, and its question, expected answer, expected
quotes, answerable flag and persona must be unchanged. The only allowed edit to an existing entry is a changed `reason`
(the reason is the audit trail for a deliberate correction). New questions need a reason too. Used by the Stop hook and CI.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = "backend/evals/golden.jsonl"
FROZEN_FIELDS = ("question", "expected_answer", "expected_quotes", "answerable", "ask_as")


def parse(text: str) -> dict[str, dict]:
    items = {}
    for line in text.splitlines():
        if line.strip():
            item = json.loads(line)
            items[item["id"]] = item
    return items


def check(base_text: str | None, current_text: str) -> list[str]:
    problems: list[str] = []
    current = parse(current_text)
    for item_id, item in current.items():
        if len(str(item.get("reason", "")).strip()) < 3:
            problems.append(f"{item_id}: every golden question needs a reason")
    if base_text is None:
        return problems
    base = parse(base_text)
    for item_id, old in base.items():
        new = current.get(item_id)
        if new is None:
            problems.append(f"{item_id}: deleted from the golden set")
            continue
        for field in FROZEN_FIELDS:
            if old.get(field) != new.get(field):
                if old.get("reason") == new.get("reason"):
                    problems.append(f"{item_id}: '{field}' changed without a new reason")
                else:
                    problems.append(f"{item_id}: '{field}' changed (new reason: {new.get('reason')!r}); needs human review in the PR")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="HEAD")
    args = parser.parse_args()
    current_text = (ROOT / GOLDEN).read_text(encoding="utf-8")
    shown = subprocess.run(["git", "show", f"{args.base}:{GOLDEN}"], cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S603, S607
    base_text = shown.stdout if shown.returncode == 0 else None
    problems = check(base_text, current_text)
    for problem in problems:
        print("GOLDEN SET:", problem, file=sys.stderr)
    if not problems:
        print(f"golden set ok ({len(parse(current_text))} questions)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
