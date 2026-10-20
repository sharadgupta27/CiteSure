"""Small text helpers shared by the chunker, the fake providers and the evaluator."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"\w+|[^\w\s]")
_WORD = re.compile(r"[a-z0-9$%.,@']+")
_BOUNDARY = re.compile(r"([.!?][\"')\]]*)\s+(?=[\"'(\[]?[A-Z])|\n+")

STOPWORDS = frozenset(
    [
        "a",
        "about",
        "after",
        "all",
        "also",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "before",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "get",
        "give",
        "got",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "no",
        "not",
        "of",
        "on",
        "one",
        "or",
        "our",
        "out",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "up",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "many",
        "much",
        "long",
        "often",
        "fast",
        "quickly",
    ]
)


def count_tokens(text: str) -> int:
    """Cheap token estimate (word and punctuation pieces). Good enough to size chunks without a tokenizer."""
    return len(_TOKEN.findall(text))


def normalise_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def stem(word: str) -> str:
    """A deliberately tiny stemmer so 'weeks' matches 'week' and 'reimbursed' matches 'reimburse'."""
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    else:
        for suffix in ("ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                word = word[: -len(suffix)]
                break
    if word.endswith("e") and len(word) > 3:
        word = word[:-1]
    return word


def words(text: str) -> list[str]:
    return [w.strip(".,'@") for w in _WORD.findall(text.lower()) if w.strip(".,'@")]


def content_terms(text: str) -> list[str]:
    """Lower-cased, stop-word-free, stemmed terms. Numbers are kept as they are."""
    return [stem(w) for w in words(text) if w not in STOPWORDS]


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of sentences. Newlines always end a sentence (list items, table rows)."""
    spans: list[tuple[int, int]] = []

    def add(start: int, end: int) -> None:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            spans.append((start, end))

    pos = 0
    for match in _BOUNDARY.finditer(text):
        add(pos, match.end(1) if match.group(1) else match.start())
        pos = match.end()
    add(pos, len(text))
    return spans
