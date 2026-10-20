from __future__ import annotations

import io
import re
from pathlib import PurePath

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.rag.parsing.builder import SectionBuilder
from app.rag.parsing.types import ParsedDocument

_HEADING = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)


def _heading_level(paragraph: Paragraph) -> int | None:
    try:
        name = paragraph.style.name if paragraph.style is not None else ""
    except (KeyError, AttributeError):
        return None
    if name.lower() == "title":
        return 1
    match = _HEADING.match(name or "")
    return int(match.group(1)) if match else None


def parse_docx(data: bytes, filename: str) -> ParsedDocument:
    doc = DocxDocument(io.BytesIO(data))
    builder = SectionBuilder()
    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            paragraph = Paragraph(child, doc)
            level = _heading_level(paragraph)
            if level is not None:
                builder.heading(level, paragraph.text)
            else:
                builder.block(paragraph.text)
        elif child.tag.endswith("}tbl"):
            table = Table(child, doc)
            for row in table.rows:
                cells: list[str] = []
                for cell in row.cells:
                    text = cell.text.strip()
                    if text and (not cells or cells[-1] != text):  # merged cells repeat their text
                        cells.append(text)
                builder.block(" | ".join(cells))
    title = (
        (doc.core_properties.title or "").strip() or builder.first_h1 or PurePath(filename).stem.replace("-", " ").title()
    )
    return ParsedDocument(title=title, sections=builder.finish())
