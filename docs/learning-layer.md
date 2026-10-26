# Learning layer (phase 4)

Reading progress, study sets, learning plans, and the summarize and compare agents. The rule that shapes all of it:
**every generated sentence still passes claim verification**, and everything a user creates here is private to that user.

## What it does

| Feature | Endpoints (operationId) | Where the facts come from |
|---|---|---|
| Reading progress | `GET/PUT/DELETE /documents/{id}/progress` (`getReadingProgress`, `updateReadingProgress`, `resetReadingProgress`), `GET /workspaces/{id}/reading-progress` (`listReadingProgress`) | The user's own reports. Nothing generated. |
| Study sets | `/workspaces/{id}/study-sets`, `/study-sets/{id}`, `/study-sets/{id}/items[/{item}]` | The user's choices and notes. A saved public paper is a title and link only; nothing is fetched. |
| Learning plans | `/workspaces/{id}/learning-plans`, `/learning-plans/{id}`, `PATCH /learning-plans/{id}/steps/{step}` | Steps, order, pages, effort and weeks are **computed** from the documents' structure. Each step's learning objective is **generated and verified**. |
| Summarize | `POST /workspaces/{id}/learning/summarize` | Verified claims quoted from the document. |
| Compare (2 to 5 documents) | `POST /workspaces/{id}/learning/compare` | Verified claims; a difference or agreement needs a quote from every document it names. |

Study sets are **not** the ACL `Collection`: a study set grants nobody access to anything. Adding a document needs read access.

## How generated text stays grounded

`services/learning/grounded.py` runs the same stages as `/ask` (`services/pipeline.py`) on chunks the agent picked:
`build_sources` (id-tagged, tag-neutralised blocks) -> `llm.generate_answer` -> `verify_draft` (fuzzy quote match >= `QUOTE_MATCH_MIN`,
then entailment) -> drop unsupported claims -> refuse if none are left. There is no switch to skip verification.
Results are stored as ordinary `answers` rows (in a thread named `Summary: ...`, `Compare: ...` or `Plan: ...`), so:

* the response is the existing `Answer` shape and the existing `AnswerView` renders it, with the source drawer;
* `GET /answers/{id}` re-checks every citation against the caller's current access;
* deleting a document scrubs its quotes from these answers (`asks.scrub_deleted_chunks`) and removes its plan steps.

What is **not** generated: step titles, section labels, pages, minutes, order and week. They are read from headings, page numbers
and token counts, so they cannot be hallucinated. Order is the study-set order; for a topic plan it is introductions
(titles like "introduction", "overview", "survey") first, then by relevance to the topic.

Plan behaviour when nothing is supported: a **study-set** plan keeps the step (it is still a real section to read) and shows a
refusal as its objective; a **topic** plan leaves the step out, and fails with 422 if no step has a supported statement.

Long documents: a summary reads `LEARNING_SUMMARY_CHUNKS` sections (evenly spread, or the best matches for the focus) and says so in `notices`.
Hierarchical (map-reduce) summarization is not done.

## Access control and isolation

* Every document id goes through `services/acl.py` (`allowed_collection_ids`). Unreadable, unknown, or other-workspace ids are the same
  404 with the same body, so existence is not revealed. For compare, one bad id makes the whole request a 404.
* Chunk and document lookups filter by the allowed collection ids in SQL (`repositories/learning_sources.py`).
* Progress, sets and plans are keyed by `user_id`; there is no admin view. A user who leaves the workspace loses sight of their rows.
* Documents the caller can no longer read disappear from sets, roll-ups, plan steps and the recent-reading list (decided by the SQL join), and
  stored objectives lose citations they can no longer read.
* Prompt injection: document text is neutralised and id-tagged exactly as for `/ask`; the user's own focus/aspect text is neutralised too; the
  models have no tools. Tests drive the fake `obedient` model through summarize, compare and plan.
* Private mode: `choose_llm(..., internal_text=True)` is used, so company text only reaches `providers.llm`, and `ensure_lane_safe` raises
  `privacy_violation` (500) before any call if that model is hosted. The agents never touch the public lane or the network.
* No document text in logs: generation failures log the exception type only and return 502.

## Data model (migration 0004)

`reading_progress(user_id, document_id, last_page, pages_read[], percent, last_opened_at)`, `study_sets`, `study_set_items`
(`kind` document | reference), `learning_plans`, `learning_plan_steps` (`answer_id` -> `answers`).
All foreign keys to documents and users cascade, so deleting a document removes progress, set items and plan steps.

## Reading progress

Pages only accumulate (`mark_read`); percent is pages read / `page_count`, or the furthest reported percent for documents without
pages (Markdown, HTML, DOCX). `frontend/src/components/ReadingProgress.tsx` is standalone, and `useTrackReading` is the hook:
it reports the page after 400 ms and marks it read after `dwellMs` (default 4000) on the same page.

**Wiring into the viewer (lead):**
`<ReadingProgress documentId={doc.id} page={currentPage} pageCount={doc.page_count} compact />` (pass `page={null}` for non-paged documents).

## Settings (`config.py`, phase 4 block)

`LEARNING_READING_WPM` (200), `LEARNING_UNIT_MINUTES` (30, reading per step), `LEARNING_MAX_PLAN_DOCUMENTS` (12), `LEARNING_MAX_PLAN_STEPS` (12,
one model call per step), `LEARNING_SUMMARY_CHUNKS` (12), `LEARNING_COMPARE_CHUNKS_PER_DOC` (3), `LEARNING_GENERATION_CONCURRENCY` (3).
The model-backed endpoints share the per-user `RATE_LIMIT_ASK_PER_MIN` budget (bucket `learn:<user>`).

## Known gaps

* Plans are built inside the request (up to `LEARNING_MAX_PLAN_STEPS` model calls, 3 at a time). With a slow local model move this to the worker.
* Document ordering is a title heuristic plus relevance, not a prerequisite analysis; a model cannot be trusted to assert prerequisites without a source.
* The summary/compare/plan prompts (`rag/generation/prompts/{summarize,compare,plan_step}_v1.md`) are new and are covered by tests with the fake model only;
  run them against a real model (and add golden questions) before relying on them.
* Compare answers one claim per document or relation; the UI groups by cited document. No contradiction detection beyond what the model states with quotes.
* Audit events for these actions are not emitted (phase 5 owns the audit log).
