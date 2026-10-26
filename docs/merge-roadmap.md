# Merging document_explorer into CiteSure

CiteSure is the base. Everything from `D:\MyProjects\document_explorer` that CiteSure lacked has been ported into
CiteSure's own stack (FastAPI, Postgres + pgvector, its own auth). Qdrant and Keycloak are not hard dependencies: the
capabilities they provided were reimplemented, or added as optional adapters (OIDC).

## Status

| Capability | Status | Where |
|---|---|---|
| Per-claim verification, refusals | CiteSure's own | [rag-design.md](rag-design.md) |
| Hybrid retrieval (lexical + vector + rerank) | CiteSure's own | [rag-design.md](rag-design.md) |
| Public literature search (arXiv, Crossref, OpenAlex, Europe PMC, Semantic Scholar) | done | [public-research.md](public-research.md) |
| Table-aware PDF parsing (PyMuPDF) | done, phase 1 | `backend/app/rag/parsing/pdf.py` |
| "Looks like a literature question" hint | done, phase 1 | `frontend/src/lib/researchIntent.ts` |
| PDF viewer, cited-quote outline, user highlights and notes | done, phase 2 | [viewer-and-inbox.md](viewer-and-inbox.md) |
| Watched-folder inbox (folder = collection = access rules) | done, phase 2 | [viewer-and-inbox.md](viewer-and-inbox.md) |
| Open-access full text on demand, budgeted, through the egress guard | done, phase 3 | [open-access-fulltext.md](open-access-fulltext.md) |
| Reading progress, study sets, learning plans, summarize and compare | done, phase 4 | [learning-layer.md](learning-layer.md) |
| Tamper-evident audit log and admin dashboard | done, phase 5 | [audit-dashboard.md](audit-dashboard.md) |
| Optional OIDC login (Keycloak, Entra, Google) | done, phase 5 | [oidc.md](oidc.md) |
| Encrypted vault for uploads, local OCR for scanned PDFs | done, phase 5 | [vault-and-ocr.md](vault-and-ocr.md) |

Cross-phase wiring done by the lead: reading progress shows in the PDF viewer toolbar; annotation, inbox, full-text and
learning actions write audit entries (ids and counts only, never question or document text).

## Not verified yet

- Real Keycloak or Entra login, real Tesseract OCR, and a Docker image build with `WITH_OCR=true` were never run; they
  are covered by mocked tests only.
- The learning prompts (summarize, compare, plan step) are tested with the fake model. They need a real-model eval and
  golden questions before anyone relies on them.
- The viewer, learning pages, inbox, dashboard and audit log were run in real Chromium against the full demo stack (fake
  models) and the private stack's API was exercised with a local model (ask, summarize, plan, audit chain). That run found a
  real bug the mocked tests could not: nginx served the PDF.js worker (`.mjs`) as `application/octet-stream`, so the viewer
  failed with "The PDF could not be displayed" (fixed in `frontend/nginx.conf`, see the deployment note in
  [viewer-and-inbox.md](viewer-and-inbox.md)).
- Answers over published research need Anthropic credit when `PUBLIC_LLM_PROVIDER=anthropic`; with no credit the screen only
  says "temporarily unavailable". A specific, safe reason for admins is still to do.

## Known gaps

- Inbox files in a first folder that matches no workspace are quarantined on disk but shown in no UI (to avoid leaking
  names across tenants).
- Highlights cannot span two PDF pages; the watcher polls instead of using file-system events.
- The open-access full-text cache is shared across workspaces; only the download budget is per workspace.
- The audit chain cannot reveal removal of the newest rows (keep a copy of `head_hash`), and someone with database
  owner rights could rewrite it.
- Plans are generated inside one request (up to 12 model calls); the UI cannot reorder study-set items yet.
- The table detector needs three or more columns, so a two-column table reads as prose. Lowering that would also split
  two-column research papers, which matters more.

## Decisions to keep in mind

- **Licence.** PyMuPDF is AGPL-3.0. Fine for an internal deployment; if CiteSure is distributed or offered as a service
  to others, publish the source under a compatible licence or swap the PDF library.
- **Hosted models.** document_explorer forbids any hosted API; CiteSure can send public-only text to Anthropic. The
  merged product keeps CiteSure's rule: private mode forbids it, normal mode allows it for public text only.
