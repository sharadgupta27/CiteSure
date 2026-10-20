"""Regex PII scanner run at ingestion. It flags chunks (and can redact) before anything is embedded or sent
to an LLM. Presidio would be more thorough; regexes cover the obvious cases without a model download."""

from __future__ import annotations

import re

_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    "us_ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone": re.compile(r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{3}[\s.-]\d{3,4}[\s.-]?\d{0,4}(?!\w)"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
}


def _luhn_ok(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 16:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def scan(text: str) -> dict[str, int]:
    """Counts of each PII type found. Empty dict means nothing was found."""
    found: dict[str, int] = {}
    for kind, pattern in _PATTERNS.items():
        matches = pattern.findall(text)
        if kind == "credit_card":
            matches = [m for m in matches if _luhn_ok(m)]
        if matches:
            found[kind] = len(matches)
    return found


def redact(text: str) -> str:
    """Replace PII with [KIND] placeholders. Applied before chunking so character offsets stay consistent."""
    for kind, pattern in _PATTERNS.items():
        if kind == "credit_card":
            text = pattern.sub(lambda m: "[CREDIT_CARD]" if _luhn_ok(m.group(0)) else m.group(0), text)
        else:
            text = pattern.sub(f"[{kind.upper()}]", text)
    return text
