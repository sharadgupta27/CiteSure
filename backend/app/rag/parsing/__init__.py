"""One parser per file type. Each returns a ParsedDocument of Sections (heading path, text, page)."""

from __future__ import annotations

from app.rag.parsing.detect import Detected, Kind, detect
from app.rag.parsing.docx import parse_docx
from app.rag.parsing.html import parse_html
from app.rag.parsing.markdown import parse_markdown
from app.rag.parsing.pdf import OcrOptions, parse_pdf
from app.rag.parsing.types import ParsedDocument, ParseError, Section

_PARSERS = {"docx": parse_docx, "html": parse_html, "markdown": parse_markdown}


def parse_document(kind: Kind, data: bytes, filename: str, *, ocr: OcrOptions | None = None) -> ParsedDocument:
    """`ocr` only matters for PDFs (scanned pages); other formats have a text layer by construction."""
    try:
        parsed = parse_pdf(data, filename, ocr=ocr) if kind == "pdf" else _PARSERS[kind](data, filename)
    except ParseError:
        raise
    except Exception as exc:  # third-party parsers raise many exception types on malformed input
        raise ParseError(f"Could not parse the {kind} file: {type(exc).__name__}") from exc
    if not parsed.sections:
        raise ParseError("The document has no text")
    return parsed


__all__ = ["Detected", "Kind", "OcrOptions", "ParseError", "ParsedDocument", "Section", "detect", "parse_document"]
