# Audit log and dashboard (phase 5)

Both pages are for **workspace admins**. The server enforces it (`acl.require_admin`): a plain member gets `403`, a stranger `404`. No setting is needed; the migration (`0005`) creates the table.

## Audit log

An append-only, tamper-evident record of who did what. Open **Audit log** in the sidebar (`/audit`).

### What is recorded

| Action | Written by | Metadata (never text) |
|---|---|---|
| `auth.login`, `auth.login_failed`, `auth.register`, `auth.oidc_login`, `auth.oidc_failed` | `services/auth.py` | method, whether the account exists, a SHA-256 of an unknown e-mail address (never the address), reason code |
| `workspace.create`, `member.add`, `group.create`, `group.member_add`, `collection.create/update/delete` | `routes_workspaces.py` | role, visibility, counts, a hash of the e-mail added to a group |
| `document.upload`, `document.delete`, `document.reindex` | `routes_documents.py` | byte size, mime type, file SHA-256 (no file name) |
| `ask` (also the streamed variant) | `routes_ask.py` | question **length**, scope, status, claim counts, egress counts |
| `feedback.create` | `routes_ask.py` | rating, comment **length** |
| `golden.*`, `eval.run` | `routes_evaluation.py` | pipeline settings, ids |
| `audit.export` | `routes_audit.py` | row count |

**Invariant:** entries hold ids, counts, lengths and hashes. `audit.sanitize_metadata` drops keys named like content (`text`, `question`, `comment`, `password`, `token`...) and cuts long strings, so a careless caller cannot put a question or a secret into the log. Tests assert that question, comment, file name and document words appear nowhere in the table.

### How it resists tampering

- Each row stores `prev_hash` and `hash = SHA-256(prev_hash, canonical JSON of the row)`. Rows get a gap-free `seq`; appends are serialised with a Postgres advisory lock so the chain never forks.
- Triggers make `UPDATE`, `DELETE` and `TRUNCATE` on `audit_log` fail, also for the application's own database role.
- **Verify chain** (page button, `GET /workspaces/{id}/audit-events/verify`) recomputes everything and reports the first entry that was changed, a gap, or a broken link.
- Honest limits: someone with database owner rights can switch the triggers off and rewrite *all* rows consistently, and removal of the **newest** rows cannot be seen from the table. The verify result shows `head_hash`: keep a copy outside the database (a ticket, a mail to yourself, a weekly job) and compare. Retention (deleting old rows) is a deliberate operator action: afterwards the oldest kept row becomes the trust anchor and the page says "starting at #N".
- Entries are written in their own transaction right after the action succeeded, so a failed login (which ends in an error and a rollback) is still kept. If writing an entry fails, the request fails (fail closed); for the streamed `ask` the answer is already on its way, so that failure is logged instead.

### Who sees what

Entries of the workspace, plus sign-in entries (no workspace) made by its members. Filters: person (id or part of an e-mail), action, date range; 25 per page; CSV export (oldest first, spreadsheet-formula safe, itself logged, 50,000 row cap). The verify check covers the whole system log, because it is one chain.

### For code that wants to add entries

```python
from app.services import audit
await audit.record(session, user, "thing.did", target=f"thing:{thing.id}", workspace_id=ws_id, metadata={"count": 3})
```

In a route, take `audit: AuditLog = Depends(audit_log)` (`app/api/deps_admin.py`) and call `await audit.record(user, ...)`. `audit.workspace_of("document", id)` finds the workspace of a collection, document, answer or golden question (look it up *before* a delete). Add the action name as a constant in `services/audit.py` and to the list in `AuditPage.tsx`.

**Still to be wired by the lead** (phases 2 to 4 do not call it yet): annotation create/delete, inbox scans and imports, full-text fetches, study sets, learning plans and the summarize/compare agents. Use one entry per user-visible action; ids and counts only.

## Dashboard

`GET /workspaces/{id}/dashboard?days=30` (7, 30, 90 in the UI): aggregates only.

| Tile or chart | Definition |
|---|---|
| Questions, per day | rows in `answers` in the period, days in UTC, empty days are zero |
| Refusal rate | refused / questions |
| Dropped-claim rate | dropped / (shown + dropped) claims |
| Latency p50 / p95 | per answer, the sum of its stage timings; Postgres `percentile_cont` |
| Cost, tokens | sums of the stored estimates (`PRICE_*` settings) |
| Documents by status, chunks | current state, counted only over collections the admin may read |
| Outbound requests | `egress` records on answers, by destination and status (`sent`, `blocked`, `failed`) |
| Feedback | helpful / (helpful + not helpful) |
| Ingestion failures | failed documents (with the parser's reason), failed `ingest_document` jobs in the period |

Charts are inline SVG with no library and nothing fetched from a CDN. Each has a text summary for screen readers and a "Show as table" view; colours are CSS variables with a dark-mode set, and series are named in a legend and by their labels, never by colour alone.
