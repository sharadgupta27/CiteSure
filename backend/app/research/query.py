"""Turns a question into a public search query: the informative keywords, nothing else.

Deterministic on purpose. A model rewriting the question could carry internal wording into the query; this keeps
only single words, in order, so no sentence from the question (or from a document) survives intact. The egress guard
still checks the result, and the user can see and edit it before it is sent (POST /public-research/preview).
"""

from __future__ import annotations

import re

from app.rag.text import STOPWORDS

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-']*")
_QUESTION_NOISE = frozenset(
    [
        "tell",
        "explain",
        "please",
        "show",
        "describe",
        "compare",
        "versus",
        "vs",
        "latest",
        "recent",
        "published",
        "research",
        "paper",
        "papers",
        "literature",
        "study",
        "studies",
        "say",
        "says",
        "said",
        "know",
        "need",
        "want",
        "like",
        "should",
        "would",
        "could",
        "between",
        "using",
        "use",
        "used",
        "find",
        "summarise",
        "summarize",
        "overview",
        "whether",
        "does",
        "doing",
        "done",
        "being",
        "made",
        "make",
        "makes",
    ]
)
MAX_TERMS = 8


def build_public_query(question: str, max_terms: int = MAX_TERMS) -> str:
    seen: dict[str, str] = {}
    for word in _WORD.findall(question):
        lowered = word.lower().strip("-'")
        if len(lowered) < 3 or lowered in STOPWORDS or lowered in _QUESTION_NOISE:
            continue
        seen.setdefault(lowered, word.strip("-'"))
    return " ".join(list(seen.values())[:max_terms])
