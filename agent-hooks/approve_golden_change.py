"""Record that a change to the golden evaluation set is intentional, with a reason. Called by the add-golden-question skill.

    python agent-hooks/approve_golden_change.py "Users reported the bot missed the sabbatical policy (ticket 123)"

The approval lasts 2 hours and only for the current git commit, so it cannot silently cover later work.
The guard hook then allows edits to backend/evals/golden*.jsonl, and `check_golden_append_only.py` verifies
that existing questions were not weakened.
"""

from __future__ import annotations

import json
import sys
import time

from common import GOLDEN_APPROVAL, head_sha


def main() -> int:
    reason = " ".join(sys.argv[1:]).strip()
    if len(reason) < 10:
        print('Usage: python agent-hooks/approve_golden_change.py "<why this golden question is being added or changed>"', file=sys.stderr)
        print("A real reason (at least 10 characters) is required.", file=sys.stderr)
        return 1
    GOLDEN_APPROVAL.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_APPROVAL.write_text(json.dumps({"approved_at": time.time(), "head": head_sha(), "reason": reason}), encoding="utf-8")
    print(f"Golden-set change approved for 2 hours on commit {head_sha()[:8]}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
