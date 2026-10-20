"""One parser per file type. Each returns a ParsedDocument of Sections (heading path, text, page)."""

from __future__ import annotations

from app.rag.parsing.detect import Detected, Kind, detect
from app.rag.parsing.docx import parse_docx
from app.rag.parsing.html import parse_html
from app.rag.parsing.markdown import parse_markdown
from app.rag.parsing.pdf import parse_pdf
from app.rag.parsing.types import ParsedDocument, ParseError, Section

_PARSERS = {"pdf": parse_pdf, "docx": parse_docx, "html": parse_html, "markdown": parse_markdown}


def parse_document(kind: Kind, data: bytes, filename: str) -> ParsedDocument:
    try:
        parsed = _PARSERS[kind](data, filename)
    except ParseError:
        raise
    except Exception as exc:  # third-party parsers raise many exception types on malformed input
        raise ParseError(f"Could not parse the {kind} file: {type(exc).__name__}") from exc
    if not parsed.sections:
        raise ParseError("The document has no text")
    return parsed


__all__ = ["Detected", "Kind", "ParseError", "ParsedDocument", "Section", "detect", "parse_document"]
