from __future__ import annotations

import io
import re
from pathlib import PurePath

from pypdf import PdfReader

from app.rag.parsing.builder import clean
from app.rag.parsing.types import ParsedDocument, ParseError, Section

_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_SOFT_WRAP = re.compile(r"(?<!\n)\n(?!\n)")


def _normalise_page(text: str) -> str:
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _SOFT_WRAP.sub(" ", text)  # a single newline inside a paragraph is only a line wrap
    paragraphs = [clean(p) for p in re.split(r"\n\s*\n", text)]
    return "\n".join(p for p in paragraphs if p)


def parse_pdf(data: bytes, filename: str) -> ParsedDocument:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ParseError("The PDF is password protected")
    sections: list[Section] = []
    for number, page in enumerate(reader.pages, start=1):
        text = _normalise_page(page.extract_text() or "")
        if text:
            sections.append(Section(heading_path=(), text=text, page=number))
    if not sections:
        raise ParseError("The PDF has no extractable text (scanned PDFs need OCR, which is not supported)")
    meta_title = (reader.metadata.title if reader.metadata else None) or ""
    title = meta_title.strip() or PurePath(filename).stem.replace("-", " ").replace("_", " ").title()
    return ParsedDocument(title=title, sections=sections, page_count=len(reader.pages))
