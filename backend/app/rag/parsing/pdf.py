"""PDF parsing with PyMuPDF: reading order, headings, repaired ligatures, and tables read row by row.

Tables matter because a plain text dump reads a table column by column, so "Keyboard | 80 dollars" becomes two
unrelated runs of words and an answer about the price cannot be quoted. Rows are rebuilt from word positions
instead, and a long table is split into slices that each repeat the header row.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

import pymupdf

from app.rag.parsing.builder import clean
from app.rag.parsing.types import ParsedDocument, ParseError, Section

log = logging.getLogger(__name__)

_TI_LIGATURE = re.compile(r"(?<=[A-Za-z])[\x13Ɵ](?=[A-Za-z])")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f�]")
_HEADING = re.compile(r"^(\d+(\.\d+)*\.?\s+)?[A-Z][A-Za-z0-9 ,:&\-/()]{2,80}$")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")

_SAME_LINE_PT = 3.0  # words whose vertical centres differ by less than this share a line
_TABLE_GAP_PT = 18.0  # a horizontal gap wider than this separates two table cells
_TABLE_MIN_ROWS = 4
_TABLE_SLICE_ROWS = 14


def repair_text(text: str) -> str:
    """Undo font-ligature damage so a quoted passage is spelled the way the reader sees it.

    Some fonts map the "ti" ligature to a control character or U+019F ("innova<ti>on"); presentation forms such as
    "fi" fold under NFKC. Whatever control characters remain are dropped.
    """
    text = unicodedata.normalize("NFKC", text)
    text = _TI_LIGATURE.sub("ti", text)
    return _CONTROL.sub("", text)


@dataclass
class _Row:
    top: float
    bottom: float
    text: str
    cells: int  # how many cell gaps the row has; 0 means ordinary prose


def _page_rows(page: Any, textpage: Any = None) -> list[_Row]:
    """Rebuild text lines from word positions so that a table is read row by row rather than column by column."""
    words = sorted(page.get_text("words", textpage=textpage), key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines: list[list[Any]] = []
    centre: float | None = None
    for word in words:
        y = (word[1] + word[3]) / 2
        if centre is not None and lines and abs(y - centre) <= _SAME_LINE_PT:
            lines[-1].append(word)
            centre = (centre * (len(lines[-1]) - 1) + y) / len(lines[-1])
        else:
            lines.append([word])
            centre = y
    rows: list[_Row] = []
    for line in lines:
        line.sort(key=lambda w: w[0])
        text, previous_right, gaps = "", None, 0
        for word in line:
            if previous_right is not None:
                if word[0] - previous_right > _TABLE_GAP_PT:
                    text += " | "
                    gaps += 1
                else:
                    text += " "
            text += repair_text(str(word[4]))
            previous_right = word[2]
        rows.append(_Row(min(w[1] for w in line), max(w[3] for w in line), text, gaps))
    return rows


def _table_runs(rows: list[_Row]) -> list[list[_Row]]:
    """Runs of consecutive multi-column rows. A short label row between two of them does not end the table."""
    runs: list[list[_Row]] = []
    current: list[_Row] = []

    def close() -> None:
        if sum(1 for r in current if r.cells >= 2) >= _TABLE_MIN_ROWS:
            runs.append(list(current))
        current.clear()

    for i, row in enumerate(rows):
        label_inside_table = (
            current and row.cells == 0 and len(row.text) < 40 and i + 1 < len(rows) and rows[i + 1].cells >= 2
        )
        if row.cells >= 2 or label_inside_table:
            current.append(row)
        else:
            close()
    close()
    return runs


def _table_texts(run: list[_Row]) -> list[str]:
    header = run[0].text
    slices: list[str] = []
    for start in range(0, len(run), _TABLE_SLICE_ROWS):
        lines = [r.text for r in run[start : start + _TABLE_SLICE_ROWS]]
        if start:
            lines.insert(0, header)  # every slice keeps the column names
        slices.append("\n".join(lines))
    return slices


def _looks_like_heading(line: str) -> bool:
    line = line.strip()
    words = line.split()
    if not 3 <= len(line) <= 90 or line.endswith((".", ",", ";")) or len(words) > 12:
        return False
    return bool(_HEADING.match(line)) and (
        line.isupper() or re.match(r"^\d+(\.\d+)*\.?\s+\S", line) is not None or len(words) <= 6
    )


def _page_blocks(page: Any, textpage: Any = None) -> list[tuple[str, bool]]:
    """The page's text as (text, is_heading) in reading order, with each table emitted once as row-wise text.

    `textpage` is an OCR text page for scanned pages; None reads the page's own text layer.
    """
    runs = _table_runs(_page_rows(page, textpage))
    spans = [(min(r.top for r in run) - 1, max(r.bottom for r in run) + 1) for run in runs]
    emitted = [False] * len(runs)
    out: list[tuple[str, bool]] = []
    for block in page.get_text("blocks", textpage=textpage):
        if len(block) < 7 or block[6] != 0:  # 0 is a text block; anything else is an image
            continue
        centre = (block[1] + block[3]) / 2
        table = next((i for i, (top, bottom) in enumerate(spans) if top <= centre <= bottom), None)
        if table is not None:
            if not emitted[table]:
                emitted[table] = True
                out += [(text, False) for text in _table_texts(runs[table])]
            continue
        raw = repair_text(str(block[4]))
        text = _HYPHEN_BREAK.sub(r"\1\2", raw)
        lines = [clean(line) for line in text.splitlines() if clean(line)]
        if not lines:
            continue
        if len(lines) == 1 and _looks_like_heading(lines[0]):
            out.append((lines[0], True))
        else:
            out.append((" ".join(lines), False))
    return out


@dataclass(frozen=True)
class OcrOptions:
    """OCR for scanned pages. Off by default; it needs Tesseract on the machine and runs entirely locally."""

    enabled: bool = False
    languages: str = "eng"  # Tesseract codes joined with "+", e.g. "eng+deu"
    dpi: int = 300
    max_pages: int = 200  # OCR is slow (seconds per page), so one huge scan cannot hold the worker for an hour


_OCR_MIN_CHARS = 20  # a page with fewer characters than this has no usable text layer (a page number is not a page)
_LANGUAGES = re.compile(r"^[A-Za-z0-9_]+(\+[A-Za-z0-9_]+)*$")


def _tessdata(languages: str) -> str:
    """The Tesseract language-data folder, or a ParseError that tells the operator how to fix it."""
    if not _LANGUAGES.match(languages):
        raise ParseError("OCR_LANGUAGES must be Tesseract language codes joined with +, for example eng+deu")
    try:
        folder = pymupdf.get_tessdata()
    except Exception:
        raise ParseError(
            "OCR is enabled but Tesseract is not installed. Install Tesseract (the Docker image: build with "
            "WITH_OCR=true) or set OCR_ENABLED=false"
        ) from None
    missing = [lang for lang in languages.split("+") if not (Path(folder) / f"{lang}.traineddata").is_file()]
    if missing:
        raise ParseError(f"OCR is enabled but Tesseract has no language data for: {', '.join(missing)}")
    return str(folder)


def _ocr_blocks(page: Any, options: OcrOptions, tessdata: str) -> list[tuple[str, bool]]:
    """Read one page with PyMuPDF's built-in Tesseract. The seam tests replace, so they never need Tesseract."""
    # full=False OCRs only the page's images and keeps any real text; a page drawn without images (text as vector
    # shapes) has nothing to find that way, so it is OCR'd as a whole.
    textpage = page.get_textpage_ocr(
        language=options.languages, dpi=options.dpi, full=not page.get_images(), tessdata=tessdata
    )
    return _page_blocks(page, textpage)


def _chars(blocks: list[tuple[str, bool]]) -> int:
    return sum(len(text) for text, _ in blocks)


class _OcrRun:
    """Per-document OCR state: checks Tesseract only when a scanned page is met, and enforces the page cap."""

    def __init__(self, options: OcrOptions) -> None:
        self.options = options
        self.done = 0
        self.skipped = 0
        self._tessdata: str | None = None

    def wants(self, page: Any, blocks: list[tuple[str, bool]]) -> bool:
        if not self.options.enabled or _chars(blocks) >= _OCR_MIN_CHARS:
            return False
        # A page with neither pictures nor drawings is genuinely blank: OCR would only burn seconds.
        return bool(page.get_images() or page.get_drawings())

    def read(self, page: Any) -> list[tuple[str, bool]]:
        if self.done >= self.options.max_pages:
            self.skipped += 1
            return []
        if self._tessdata is None:
            self._tessdata = _tessdata(self.options.languages)
        self.done += 1
        return _ocr_blocks(page, self.options, self._tessdata)


def parse_pdf(data: bytes, filename: str, *, ocr: OcrOptions | None = None) -> ParsedDocument:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ParseError("The PDF could not be opened") from exc
    run = _OcrRun(ocr or OcrOptions())
    try:
        if doc.is_encrypted:
            raise ParseError("The PDF is password protected")
        outline = {page: title.strip() for _level, title, page in reversed(doc.get_toc(simple=True)) if title.strip()}
        sections: list[Section] = []
        heading = ""
        for number in range(1, doc.page_count + 1):
            heading = outline.get(number, heading)
            texts: list[str] = []
            page = doc.load_page(number - 1)
            blocks = _page_blocks(page)
            if run.wants(page, blocks):
                scanned = run.read(page)
                if _chars(scanned) > _chars(blocks):
                    blocks = scanned
            for text, is_heading in blocks:
                if is_heading:
                    # The heading stays in the passage as well as in the path: "CURRENTLY NOT ON OFFER" changes the
                    # meaning of the lines below it, and a quote has to carry that meaning.
                    _flush(sections, heading, texts, number)
                    heading = text
                texts.append(text)
            _flush(sections, heading, texts, number)
        if run.done:
            log.info("ocr pages_read=%d pages_skipped=%d", run.done, run.skipped)
        if not sections:
            if not run.options.enabled:
                raise ParseError("The PDF has no extractable text (scanned PDFs need OCR, which is not supported)")
            if run.skipped:
                raise ParseError(f"The PDF has no extractable text in its first {run.options.max_pages} OCR'd pages")
            raise ParseError("The PDF has no extractable text, and OCR found none either")
        meta_title = ((doc.metadata or {}).get("title") or "").strip()
        title = meta_title or PurePath(filename).stem.replace("-", " ").replace("_", " ").title()
        return ParsedDocument(title=title, sections=sections, page_count=doc.page_count)
    finally:
        doc.close()


def _flush(sections: list[Section], heading: str, texts: list[str], page: int) -> None:
    if texts:
        sections.append(Section(heading_path=(heading,) if heading else (), text="\n".join(texts), page=page))
        texts.clear()
