from __future__ import annotations

from pathlib import PurePath

from bs4 import BeautifulSoup, Tag

from app.rag.parsing.builder import SectionBuilder
from app.rag.parsing.types import ParsedDocument

_HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
_BLOCKS = [*_HEADINGS, "p", "li", "tr", "pre", "blockquote", "dt", "dd", "figcaption"]
_NOISE = ["script", "style", "nav", "footer", "noscript", "template", "iframe"]


def parse_html(data: bytes, filename: str) -> ParsedDocument:
    soup = BeautifulSoup(data.decode("utf-8"), "html.parser")
    for tag in soup(_NOISE):
        tag.decompose()
    builder = SectionBuilder()
    root = soup.body or soup
    for element in root.find_all(_BLOCKS):
        if not isinstance(element, Tag) or element.find(_BLOCKS):
            continue  # only leaf blocks, so nested lists and paragraphs are not counted twice
        if element.name in _HEADINGS:
            builder.heading(int(element.name[1]), element.get_text(" "))
        elif element.name == "tr":
            cells = [c.get_text(" ", strip=True) for c in element.find_all(["td", "th"])]
            builder.block(" | ".join(c for c in cells if c))
        else:
            builder.block(element.get_text(" "))
    title = (
        (soup.title.get_text(strip=True) if soup.title else "")
        or builder.first_h1
        or PurePath(filename).stem.replace("-", " ").title()
    )
    return ParsedDocument(title=title, sections=builder.finish())
