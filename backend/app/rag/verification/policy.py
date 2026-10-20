"""What happens after verification. The policy is deliberately tiny and easy to audit:

- keep only claims that passed BOTH checks;
- if none are left, refuse, and point at the closest sources the caller may read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.rag.types import ScoredChunk

REFUSAL_MESSAGE = "I don't have information on that in the documents available to you."
CLOSEST_SOURCES = 3


@dataclass(frozen=True)
class RefusalInfo:
    reason: Literal["no_sources", "no_supported_claims"]
    message: str
    closest: list[ScoredChunk]


def closest_sources(retrieved: list[ScoredChunk], limit: int = CLOSEST_SOURCES) -> list[ScoredChunk]:
    """Top chunks, one per document, in retrieval order. These were retrieved under the caller's ACL."""
    seen: set[object] = set()
    picked: list[ScoredChunk] = []
    for chunk in retrieved:
        if chunk.document_id not in seen:
            seen.add(chunk.document_id)
            picked.append(chunk)
        if len(picked) == limit:
            break
    return picked


def refusal_for(retrieved: list[ScoredChunk]) -> RefusalInfo:
    reason: Literal["no_sources", "no_supported_claims"] = "no_supported_claims" if retrieved else "no_sources"
    return RefusalInfo(reason=reason, message=REFUSAL_MESSAGE, closest=closest_sources(retrieved))
