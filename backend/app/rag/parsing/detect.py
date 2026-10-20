"""Decide what a file is from its bytes. The filename and the client's Content-Type are never trusted."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Literal

from app.errors import UnsupportedMedia

Kind = Literal["pdf", "docx", "html", "markdown"]

MIME: dict[Kind, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html",
    "markdown": "text/markdown",
}

_MAX_ZIP_UNCOMPRESSED = 200 * 1024 * 1024
_MAX_ZIP_MEMBERS = 2000
_HTML_HINTS = ("<!doctype html", "<html", "<body", "<h1", "<p>", "<div")


@dataclass(frozen=True)
class Detected:
    kind: Kind
    mime: str


def detect(data: bytes) -> Detected:
    if not data:
        raise UnsupportedMedia("The file is empty")
    if data.startswith(b"%PDF-"):
        return Detected("pdf", MIME["pdf"])
    if data.startswith(b"PK\x03\x04"):
        _check_docx(data)
        return Detected("docx", MIME["docx"])
    if b"\x00" in data[:4096]:
        raise UnsupportedMedia("Binary files other than PDF and DOCX are not supported")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnsupportedMedia("Text files must be UTF-8") from exc
    head = text[:2048].lower()
    if any(hint in head for hint in _HTML_HINTS):
        return Detected("html", MIME["html"])
    return Detected("markdown", MIME["markdown"])


def _check_docx(data: bytes) -> None:
    """A DOCX is a zip. Reject other zips, and zip bombs, before any parser touches them."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ZIP_MEMBERS:
                raise UnsupportedMedia("Archive has too many entries")
            if sum(i.file_size for i in infos) > _MAX_ZIP_UNCOMPRESSED:
                raise UnsupportedMedia("Archive expands to too much data")
            names = {i.filename for i in infos}
    except zipfile.BadZipFile as exc:
        raise UnsupportedMedia("Corrupt archive") from exc
    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
        raise UnsupportedMedia("Only PDF, DOCX, Markdown and HTML are supported")
