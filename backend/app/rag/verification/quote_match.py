"""Verification stage 1: does the quoted text really exist in the cited chunk? (Deterministic, no LLM.)

This catches fabricated quotes cheaply. It is a fuzzy match (>= QUOTE_MATCH_MIN) because models sometimes
change whitespace, curly quotes or a trailing period when copying.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

_SAME_LENGTH_MAP = str.maketrans(
    {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " ", "\t": " ", "\n": " ", "\r": " "}
)


@dataclass(frozen=True)
class QuoteMatch:
    score: float  # 0..1
    start: int  # span of the best match inside the chunk text, usable for highlighting
    end: int


def _fold(text: str) -> str:
    """Normalise without changing the string's length, so match offsets still index the original text."""
    folded = text.translate(_SAME_LENGTH_MAP)
    lowered = folded.lower()
    return lowered if len(lowered) == len(folded) else folded


def match_quote(quote: str, chunk_text: str, *, min_chars: int = 12) -> QuoteMatch:
    needle = _fold(quote.strip())
    haystack = _fold(chunk_text)
    if len(needle) < min_chars:
        return QuoteMatch(0.0, 0, 0)  # a 3-letter "quote" matches almost anywhere and proves nothing
    exact = haystack.find(needle)
    if exact >= 0:
        return QuoteMatch(1.0, exact, exact + len(needle))
    alignment = fuzz.partial_ratio_alignment(needle, haystack)
    if alignment is None:
        return QuoteMatch(0.0, 0, 0)
    return QuoteMatch(alignment.score / 100.0, alignment.dest_start, alignment.dest_end)
