from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Section:
    """A run of text under one heading. `page` is set for page-based formats (PDF)."""

    heading_path: tuple[str, ...]
    text: str
    page: int | None = None


@dataclass
class ParsedDocument:
    title: str
    sections: list[Section] = field(default_factory=list)
    page_count: int | None = None


class ParseError(Exception):
    """The file is valid enough to upload but its content could not be parsed."""
