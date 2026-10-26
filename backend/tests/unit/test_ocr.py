"""OCR for scanned PDFs. Tesseract is mocked except in the one test that skips itself when it is not installed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf
import pytest

from app.rag.parsing import OcrOptions, ParseError, parse_document
from app.rag.parsing import pdf as pdf_module

SCANNED_TEXT = "The reimbursement limit for taxi fares is fifty dollars per trip."


def _text_page_pdf(*texts: str) -> bytes:
    doc = pymupdf.open()
    for text in texts:
        doc.new_page().insert_text((72, 100), text, fontsize=16)
    return doc.tobytes()


def scanned_pdf(*texts: str, blank_pages: int = 0) -> bytes:
    """A PDF whose pages are only pictures of text, like the output of a scanner."""
    source = pymupdf.open(stream=_text_page_pdf(*texts), filetype="pdf")
    scan = pymupdf.open()
    for page in source:
        picture = page.get_pixmap(dpi=200)
        target = scan.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, pixmap=picture)
    for _ in range(blank_pages):
        scan.new_page()
    return scan.tobytes()


@pytest.fixture
def fake_tesseract(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Pretend Tesseract is installed and 'read' each scanned page; returns the page numbers it was asked to read."""
    asked: list[int] = []
    monkeypatch.setattr(pdf_module, "_tessdata", lambda languages: "/fake/tessdata")

    def fake_read(page: Any, options: OcrOptions, tessdata: str) -> list[tuple[str, bool]]:
        asked.append(page.number + 1)
        return [(f"Scanned page {page.number + 1}. {SCANNED_TEXT}", False)]

    monkeypatch.setattr(pdf_module, "_ocr_blocks", fake_read)
    return asked


ON = OcrOptions(enabled=True)


def test_a_scanned_page_is_still_rejected_when_ocr_is_off() -> None:
    with pytest.raises(ParseError, match="no extractable text"):
        parse_document("pdf", scanned_pdf(SCANNED_TEXT), "scan.pdf")
    with pytest.raises(ParseError, match="scanned PDFs need OCR, which is not supported"):
        parse_document("pdf", scanned_pdf(SCANNED_TEXT), "scan.pdf", ocr=OcrOptions(enabled=False))


def test_ocr_text_becomes_sections_with_the_right_page_numbers(fake_tesseract: list[int]) -> None:
    doc = parse_document("pdf", scanned_pdf("one", "two", "three"), "scan.pdf", ocr=ON)
    assert fake_tesseract == [1, 2, 3]
    assert [s.page for s in doc.sections] == [1, 2, 3]
    assert doc.page_count == 3
    assert "Scanned page 2." in doc.sections[1].text and "fifty dollars" in doc.sections[1].text


def test_pages_with_a_text_layer_are_not_ocrd(fake_tesseract: list[int]) -> None:
    mixed = pymupdf.open(stream=_text_page_pdf("A page with a perfectly good text layer, long enough to trust."))
    mixed.insert_pdf(pymupdf.open(stream=scanned_pdf("scanned"), filetype="pdf"))
    doc = parse_document("pdf", mixed.tobytes(), "mixed.pdf", ocr=ON)
    assert fake_tesseract == [2]
    assert [s.page for s in doc.sections] == [1, 2]
    assert "perfectly good text layer" in doc.sections[0].text


def test_blank_pages_are_not_sent_to_ocr(fake_tesseract: list[int]) -> None:
    doc = parse_document("pdf", scanned_pdf("scanned", blank_pages=2), "scan.pdf", ocr=ON)
    assert fake_tesseract == [1]
    assert [s.page for s in doc.sections] == [1]


def test_max_pages_caps_how_many_pages_are_read(fake_tesseract: list[int]) -> None:
    data = scanned_pdf("a", "b", "c", "d")
    doc = parse_document("pdf", data, "scan.pdf", ocr=OcrOptions(enabled=True, max_pages=2))
    assert fake_tesseract == [1, 2]
    assert [s.page for s in doc.sections] == [1, 2]
    assert doc.page_count == 4


def test_nothing_read_within_the_cap_is_an_error_that_names_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_module, "_tessdata", lambda languages: "/fake")
    monkeypatch.setattr(pdf_module, "_ocr_blocks", lambda page, options, tessdata: [])
    data = scanned_pdf("a", "b", "c")
    with pytest.raises(ParseError, match="first 2 OCR'd pages"):
        parse_document("pdf", data, "scan.pdf", ocr=OcrOptions(enabled=True, max_pages=2))
    with pytest.raises(ParseError, match="OCR found none"):
        parse_document("pdf", scanned_pdf("a"), "scan.pdf", ocr=ON)


def test_ocr_on_but_tesseract_missing_gives_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_tessdata(*args: object, **kwargs: object) -> str:
        raise RuntimeError("No tessdata specified and Tesseract is not installed")

    monkeypatch.setattr(pymupdf, "get_tessdata", no_tessdata)
    with pytest.raises(ParseError, match="Tesseract is not installed") as caught:
        parse_document("pdf", scanned_pdf(SCANNED_TEXT), "scan.pdf", ocr=ON)
    assert "WITH_OCR=true" in str(caught.value)


def test_missing_language_data_is_named(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "eng.traineddata").write_bytes(b"x")
    monkeypatch.setattr(pymupdf, "get_tessdata", lambda *a, **k: str(tmp_path))
    with pytest.raises(ParseError, match="no language data for: deu"):
        parse_document("pdf", scanned_pdf(SCANNED_TEXT), "scan.pdf", ocr=OcrOptions(enabled=True, languages="eng+deu"))


@pytest.mark.parametrize("languages", ["", "../../etc", "eng+", "eng deu"])
def test_language_setting_is_validated(languages: str) -> None:
    with pytest.raises(ParseError, match="OCR_LANGUAGES"):
        parse_document("pdf", scanned_pdf(SCANNED_TEXT), "scan.pdf", ocr=OcrOptions(enabled=True, languages=languages))


def test_tesseract_is_only_needed_when_a_scanned_page_turns_up(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> str:
        raise AssertionError("Tesseract must not be consulted for a PDF that has text")

    monkeypatch.setattr(pymupdf, "get_tessdata", explode)
    doc = parse_document("pdf", _text_page_pdf("A normal page with plenty of selectable text on it."), "ok.pdf", ocr=ON)
    assert doc.sections


def test_the_ocr_options_are_a_frozen_dataclass_with_safe_defaults() -> None:
    options = OcrOptions()
    assert (options.enabled, options.languages, options.dpi, options.max_pages) == (False, "eng", 300, 200)
    with pytest.raises(AttributeError):
        options.enabled = True  # type: ignore[misc]


def _tesseract_installed() -> bool:
    try:
        return (Path(pymupdf.get_tessdata()) / "eng.traineddata").is_file()
    except Exception:
        return False


@pytest.mark.skipif(not _tesseract_installed(), reason="Tesseract with English data is not installed")
def test_real_ocr_reads_a_rendered_scan() -> None:
    doc = parse_document("pdf", scanned_pdf(SCANNED_TEXT), "scan.pdf", ocr=OcrOptions(enabled=True, dpi=200))
    text = " ".join(s.text for s in doc.sections).lower()
    assert "reimbursement" in text and "taxi" in text
    assert [s.page for s in doc.sections] == [1]
