from __future__ import annotations

import re

from app.rag.parsing.types import Section

_WS = re.compile(r"[ \t\r\f\v\xa0]+")  # \xa0 is the non-breaking space common in Word and HTML


def clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


class SectionBuilder:
    """Turns a stream of (heading, block) events into Sections, one per heading."""

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []
        self._blocks: list[str] = []
        self._sections: list[Section] = []
        self.first_h1: str | None = None

    def heading(self, level: int, text: str) -> None:
        text = clean(text)
        if not text:
            return
        self._flush()
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, text))
        if level == 1 and self.first_h1 is None:
            self.first_h1 = text

    def block(self, text: str) -> None:
        text = clean(text)
        if text:
            self._blocks.append(text)

    def _flush(self) -> None:
        if self._blocks:
            path = tuple(h for _, h in self._stack)
            self._sections.append(Section(heading_path=path, text="\n".join(self._blocks)))
        self._blocks = []

    def finish(self) -> list[Section]:
        self._flush()
        return self._sections
