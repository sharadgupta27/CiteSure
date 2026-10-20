---
name: ingest-new-doc-type
description: Add support for a new uploadable document type (for example PPTX, RTF, EPUB or CSV) end to end: magic-byte detection, a parser that returns Sections, fixtures, tests and an eval run. Use when someone asks CiteSure to accept a new file format or reports that a format parses badly.
---

# Add a new document type

One parser per file type, all returning the same `Section{heading_path, text, page}` structure, so the chunker, the
retriever and the citation viewer need no change. Follow the steps in order; each step has a check.

## Steps

1. **Plan in 3 bullets**: the format, how to detect it by magic bytes, what counts as a heading, what to do with tables and images.
   Ask before adding a dependency (CLAUDE.md rule 6); prefer the standard library.
2. **Detection** in `backend/app/rag/parsing/detect.py`: decide by bytes, never by filename or MIME type. If the format is a ZIP
   container (PPTX, EPUB), check the required member names and keep the zip-bomb limits. Add the kind to `Kind` and `MIME`.
3. **Parser** `backend/app/rag/parsing/<kind>.py`: `parse_<kind>(data: bytes, filename: str) -> ParsedDocument`.
   Use `SectionBuilder` (headings, blocks) so heading paths are consistent. Register it in `parsing/__init__.py` (`_PARSERS`).
   Raise `ParseError` with a helpful message for unreadable files; never let a third-party exception escape unwrapped.
4. **Fixtures**: add a small sample to `backend/tests/fixtures/` (generate it in `make_fixtures.py` when it is binary).
5. **Tests** (all mandatory):
   - `tests/unit/test_parsers.py`: detection, headings and heading paths, table/list handling, a corrupt file raises `ParseError`.
   - `tests/integration/test_ingestion.py`: add the fixture to the parametrised "every supported format" test (status `ready`, mime, chunks).
   - Chunk offsets are tested generically by `test_chunker.py`; if the parser produces pages, assert `page_start/page_end`.
6. **Contract**: if the upload description in `openapi.yaml` lists supported formats, update it (use the `review-api-change` skill),
   then `cd frontend && npm run gen:api`. The frontend `accept=` list in `DocumentsPage.tsx` must include the new extension.
7. **Measure** (CLAUDE.md rule 3): add 2-3 golden questions for the new format with the `add-golden-question` skill, then run
   `cd backend && uv run python -m app.evals.run --matrix evals/experiments.yaml` and record before/after in `docs/eval-results.md`.
8. **Docs and log**: update `docs/rag-design.md` (parsing table), tick `plan.md` if relevant, add an entry to `docs/ai-workflow.md`.

## Done when

`uv run pytest -m "not integration"` and `uv run pytest -m integration` pass, `ruff` and `mypy` are clean, the new format uploads through the UI,
and a citation into that file highlights the right words.

## Guardrails

- Uploaded files are untrusted: size limits, magic bytes, zip-bomb limits stay in place. No `eval`, no shelling out to converters.
- Do not log document text. Log ids and sizes.
