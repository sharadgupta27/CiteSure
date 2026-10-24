"""The egress guard: decides whether a piece of text may leave the system.

Everything that goes to the public lane (a search query, or the question handed to a hosted model) passes through
`EgressGuard.check` first. The checks are deterministic and cheap, and a refusal carries only machine-readable reason
codes: the offending text is never echoed or logged, because that text is exactly what must not leak.

Defence in depth: this is the application-level control. The network-level control (the allow-list proxy and the
internal-only Docker network in docker-compose.private.yml) still holds if this code has a bug.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from app.config import Settings
from app.observability import EGRESS_DECISIONS
from app.rag import pii

log = logging.getLogger("citesure.egress")

Kind = Literal["query", "question"]

_SECRETS: dict[str, re.Pattern[str]] = {
    "api_key": re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"),
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,})"),
    "long_hex": re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
}
_INTERNAL_ADDRESS = re.compile(
    r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01])|127\.\d{1,3})\.\d{1,3}\.\d{1,3}\b"
    r"|\b[\w-]+(?:\.[\w-]+)*\.(?:internal|corp|intranet|lan|local)\b",
    re.IGNORECASE,
)
_MARKERS = re.compile(
    r"\b(?:internal use only|internal only|do not distribute|company confidential|strictly confidential|"
    r"proprietary and confidential)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z0-9]+")
MAX_PHRASES = 400  # a 1000-character question has at most ~170 words; this bounds the work for any input
MIN_NAME_CHARS = 6


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reasons: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        return ", ".join(self.reasons) if self.reasons else "ok"


class InternalCorpus(Protocol):
    """What the guard needs to know about the company's documents. It only ever answers yes/no or returns names."""

    async def contains_any_phrase(self, phrases: list[list[str]]) -> bool: ...

    async def names(self) -> list[str]: ...


def normalised_words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def word_windows(words: list[str], size: int) -> list[list[str]]:
    if len(words) < size:
        return []
    windows = [words[i : i + size] for i in range(len(words) - size + 1)]
    if len(windows) > MAX_PHRASES:  # evenly spaced sample, so a very long input cannot turn into a long query
        step = len(windows) / MAX_PHRASES
        windows = [windows[int(i * step)] for i in range(MAX_PHRASES)]
    return windows


class EgressGuard:
    def __init__(self, settings: Settings, corpus: InternalCorpus | None) -> None:
        self._settings = settings
        self._corpus = corpus
        self._deny = [re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.IGNORECASE) for t in settings.deny_term_list]
        self._canaries = [c.lower() for c in settings.canary_list]
        self._allow = set(settings.allow_term_list)

    async def check(self, text: str, *, kind: Kind) -> Decision:
        reasons = self._static_reasons(text, kind) + await self._corpus_reasons(text)
        decision = Decision(allowed=not reasons, reasons=tuple(dict.fromkeys(reasons)))
        EGRESS_DECISIONS.labels(kind=kind, decision="allowed" if decision.allowed else "blocked").inc()
        if not decision.allowed:
            log.warning("egress blocked kind=%s reasons=%s chars=%d", kind, decision.summary, len(text))  # never the text
        return decision

    def _static_reasons(self, text: str, kind: Kind) -> list[str]:
        reasons: list[str] = []
        if not text.strip():
            return ["empty"]
        if kind == "query" and len(text) > self._settings.egress_max_query_chars:
            reasons.append("too_long")
        reasons += [f"pii:{name}" for name in pii.scan(text)]
        reasons += [f"secret:{name}" for name, pattern in _SECRETS.items() if pattern.search(text)]
        if _INTERNAL_ADDRESS.search(text):
            reasons.append("internal_address")
        if _MARKERS.search(text):
            reasons.append("confidential_marker")
        if any(pattern.search(text) for pattern in self._deny):
            reasons.append("deny_term")
        lowered = text.lower()
        if any(canary in lowered for canary in self._canaries):
            reasons.append("canary")
        return reasons

    async def _corpus_reasons(self, text: str) -> list[str]:
        if self._corpus is None:
            return []
        reasons: list[str] = []
        words = normalised_words(text)
        phrases = word_windows(words, self._settings.egress_overlap_words)
        if phrases and await self._corpus.contains_any_phrase(phrases):
            reasons.append("copied_from_documents")
        if self._settings.block_internal_titles and await self._mentions_internal_name(" ".join(words)):
            reasons.append("internal_name")
        return reasons

    async def _mentions_internal_name(self, normalised_text: str) -> bool:
        assert self._corpus is not None
        padded = f" {normalised_text} "
        for name in await self._corpus.names():
            candidate = " ".join(normalised_words(name))
            if len(candidate) < MIN_NAME_CHARS or candidate in self._allow:
                continue
            if f" {candidate} " in padded:
                return True
        return False
