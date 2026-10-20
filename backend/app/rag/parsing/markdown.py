from __future__ import annotations

from pathlib import PurePath

from markdown_it import MarkdownIt
from markdown_it.token import Token

from app.rag.parsing.builder import SectionBuilder
from app.rag.parsing.types import ParsedDocument


def _inline_text(token: Token) -> str:
    parts: list[str] = []
    for child in token.children or []:
        if child.type in {"text", "code_inline"}:
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append(" ")
    return "".join(parts) if token.children is not None else token.content


def parse_markdown(data: bytes, filename: str) -> ParsedDocument:
    tokens = MarkdownIt("commonmark").enable("table").parse(data.decode("utf-8"))
    builder = SectionBuilder()
    row: list[str] | None = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.type == "heading_open":
            builder.heading(int(token.tag[1]), _inline_text(tokens[i + 1]))
            i += 3
            continue
        if token.type == "tr_open":
            row = []
        elif token.type == "tr_close" and row is not None:
            builder.block(" | ".join(cell for cell in row if cell))
            row = None
        elif token.type == "inline":
            text = _inline_text(token)
            if row is not None:
                row.append(text.strip())
            else:
                builder.block(text)
        elif token.type in {"fence", "code_block"}:
            builder.block(token.content)
        i += 1
    sections = builder.finish()
    title = builder.first_h1 or PurePath(filename).stem.replace("-", " ").replace("_", " ").title()
    return ParsedDocument(title=title, sections=sections)
