"""Parsers (fixture files) and upload type detection by magic bytes."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.errors import UnsupportedMedia
from app.rag.parsing import ParseError, detect, parse_document

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# --- detection ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "kind"),
    [("sample.pdf", "pdf"), ("sample.docx", "docx"), ("sample.html", "html"), ("sample.md", "markdown")],
)
def test_detects_each_supported_type(name: str, kind: str) -> None:
    assert detect(load(name)).kind == kind


def test_filename_and_content_type_are_irrelevant_only_bytes_count() -> None:
    assert detect(b"%PDF-1.4 anything").kind == "pdf"  # even if it was uploaded as "notes.txt"
    assert detect(b"# just markdown").kind == "markdown"  # even if it was uploaded as "report.pdf"


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"MZ\x90\x00\x03\x00\x00\x00",  # Windows executable
        b"\x7fELF\x02\x01\x01\x00",  # Linux executable
        b"\x89PNG\r\n\x1a\n\x00\x00",  # image
        b"\xff\xfe\x00\x00binary",
    ],
)
def test_rejects_binaries_and_empty_files(payload: bytes) -> None:
    with pytest.raises(UnsupportedMedia):
        detect(payload)


def test_rejects_a_zip_that_is_not_a_docx() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(UnsupportedMedia):
        detect(buffer.getvalue())


def test_rejects_a_zip_bomb() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<x/>")
        archive.writestr("word/document.xml", "0" * (210 * 1024 * 1024))  # ~200 KB compressed, 210 MB expanded
    assert len(buffer.getvalue()) < 1024 * 1024
    with pytest.raises(UnsupportedMedia):
        detect(buffer.getvalue())


def test_rejects_non_utf8_text() -> None:
    with pytest.raises(UnsupportedMedia):
        detect("héllo".encode("latin-1") + b" more text")


# --- markdown -------------------------------------------------------------------------------
def test_markdown_sections_headings_lists_and_tables() -> None:
    doc = parse_document("markdown", load("sample.md"), "sample.md")
    assert doc.title == "Sample Policy"
    by_path = {s.heading_path: s.text for s in doc.sections}
    assert by_path[("Sample Policy",)].startswith("Intro text before any subsection.")
    assert "Rule one: always wear a badge." in by_path[("Sample Policy", "Rules")]
    assert "Rule two: report incidents within 24 hours." in by_path[("Sample Policy", "Rules")].split("\n")[1]
    assert "Basic | 100" in by_path[("Sample Policy", "Rules", "Details")]
    assert "docs/" in by_path[("Sample Policy", "Closing")]


def test_markdown_without_h1_uses_the_filename_as_title() -> None:
    doc = parse_document("markdown", b"just a paragraph of text", "my-handbook.md")
    assert doc.title == "My Handbook"


# --- html -----------------------------------------------------------------------------------
def test_html_drops_scripts_styles_nav_and_footer() -> None:
    doc = parse_document("html", load("sample.html"), "sample.html")
    text = "\n".join(s.text for s in doc.sections)
    assert doc.title == "Office Hours"
    assert "open from 8 to 18" in text
    assert "do not index" not in text
    assert "color: red" not in text
    assert "Home | About" not in text
    assert "Copyright" not in text
    assert "New Year" in text
    assert "Friday | 8 to 14" in text


def test_html_heading_paths() -> None:
    doc = parse_document("html", load("sample.html"), "sample.html")
    assert ("Office Hours", "Holidays") in {s.heading_path for s in doc.sections}


# --- docx -----------------------------------------------------------------------------------
def test_docx_headings_paragraphs_and_tables() -> None:
    doc = parse_document("docx", load("sample.docx"), "sample.docx")
    assert doc.title == "Equipment Handbook"
    by_path = {s.heading_path: s.text for s in doc.sections}
    assert "Laptops are replaced after 3 years." in by_path[("Equipment Handbook", "Laptops")]
    monitors = by_path[("Equipment Handbook", "Monitors")]
    assert "Keyboard | 80 dollars" in monitors
    assert "Headset | 120 dollars" in monitors


# --- pdf ------------------------------------------------------------------------------------
def test_pdf_has_one_section_per_page_with_page_numbers() -> None:
    doc = parse_document("pdf", load("sample.pdf"), "sample.pdf")
    assert doc.page_count == 2
    assert doc.title == "Travel Reimbursement"
    assert [s.page for s in doc.sections] == [1, 2]
    assert "taxi fares up to 50 dollars" in doc.sections[0].text
    assert "need approval from a director" in doc.sections[1].text


def test_corrupt_files_raise_parse_error_not_a_crash() -> None:
    with pytest.raises(ParseError):
        parse_document("pdf", b"%PDF-1.4 this is not really a pdf", "bad.pdf")
    with pytest.raises(ParseError):
        parse_document("docx", b"PK\x03\x04garbage", "bad.docx")


def test_empty_markdown_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_document("markdown", b"   \n\n  ", "empty.md")
