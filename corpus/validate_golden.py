"""Check that every expected quote in the golden set exists verbatim in the demo corpus.

Standard library only, so hooks and CI can run it anywhere:
    python corpus/validate_golden.py
Exit code 1 if a quote is missing, an id is duplicated, or the 30/10 split is wrong.
"""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "backend" / "evals" / "golden.jsonl"
CORPUS = ROOT / "corpus" / "demo"


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def document_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        parser = _Text()
        parser.feed(raw)
        raw = " ".join(parser.parts)
    return normalise(raw)


def main() -> int:
    texts = {p.name: document_text(p) for p in CORPUS.rglob("*") if p.suffix in {".md", ".html"}}
    problems: list[str] = []
    ids: set[str] = set()
    answerable = 0
    total = 0
    for line_no, line in enumerate(GOLDEN.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        total += 1
        answerable += bool(item["answerable"])
        if item["id"] in ids:
            problems.append(f"line {line_no}: duplicate id {item['id']}")
        ids.add(item["id"])
        if item["answerable"] and not item["expected_quotes"]:
            problems.append(f"{item['id']}: answerable question without an expected quote")
        for expected in item["expected_quotes"]:
            doc = texts.get(expected["document"])
            if doc is None:
                problems.append(f"{item['id']}: unknown document {expected['document']}")
            elif normalise(expected["quote"]) not in doc:
                problems.append(f"{item['id']}: quote not found in {expected['document']}: {expected['quote']!r}")
    if (total, answerable) != (40, 30):
        problems.append(f"expected 40 questions with 30 answerable, found {total} with {answerable}")
    for problem in problems:
        print("FAIL", problem, file=sys.stderr)
    print(f"{total} questions ({answerable} answerable), {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
