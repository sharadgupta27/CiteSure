# CiteSure - Product Spec

> Answers you can verify: document Q&A with checked citations and permission-aware retrieval. Build status: [plan.md](plan.md).

## 1. Problem

Employees lose hours searching handbooks, policies and manuals. Generic chatbots cannot show *where* an answer came from, so nobody trusts them for HR, compliance or security questions, and many internal "chat with your docs" tools leak documents across permission boundaries.

CiteSure promises three things:

1. **Every sentence carries a citation** (document, section or page, and the quoted words).
2. **Every citation is verified** before the user sees it. Unsupported claims are dropped; if none survive, the answer is *"I don't have information on that"*.
3. **Access control lives inside retrieval.** Chunks a user may not read are never fetched, so they cannot leak into an answer, a count or a timing signal.

## 2. Personas

| Persona | Goal |
|---|---|
| **Employee (Eva)** | A trustworthy answer in seconds, e.g. "how many weeks of parental leave do I get?" |
| **HR member (Hana)** | Ask about confidential People-Ops documents with the same tool |
| **Knowledge-base admin (Adam)** | Own the documents, the access rules and the answer quality |
| **Coding agent (service user)** | Diagnose a bad answer by inspecting retrieval, under the same access rules as people |

## 3. User stories and acceptance criteria

| # | Story | Acceptance criteria |
|---|---|---|
| D1 | An admin creates a workspace with collections and groups | A collection is readable by the whole workspace or by listed groups only; workspace admins read everything |
| D2 | An admin uploads PDF, DOCX, Markdown or HTML | Type checked by **magic bytes**; max 20 MB; a duplicate (same sha256) in a collection returns 409; status moves `queued → parsing → embedding → ready` (or `failed`) |
| D3 | An admin deletes or reindexes a document | Delete removes the document, chunks, embeddings and file; reindex replaces chunks atomically |
| Q1 | An employee asks a question | The answer is a list of claims, each with ≥ 1 citation quoting a retrieved chunk |
| Q2 | The employee checks a citation | Clicking it opens the source (or the real PDF page) with the quoted words highlighted |
| Q3 | No unverified claim is shown | Each claim passed the quote match (≥ 0.9) **and** the entailment check |
| Q4 | The documents don't answer the question | Status `refused`, "I don't have information on that", and links to the closest readable sources |
| Q5 | Restricted content stays restricted | A question only a restricted collection answers is refused; restricted text never appears in any answer, citation, chunk, file or diagnostics endpoint |
| Q6 | Progress is visible while waiting | `/ask/stream` emits `retrieving`, `generating`, `verifying`, then the answer |
| Q7 | A poisoned document can't hijack the system | Instructions inside documents are treated as data |
| F1 | An employee gives thumbs up/down with a comment | Stored with the answer id and user id |
| F2 | An admin promotes feedback to the golden set | Creates a golden question (source `feedback`) with a stated reason |
| E1 | An admin runs and compares evaluations | Recall@k, MRR, faithfulness, citation precision/recall and refusal accuracy, per run and side by side |
| P1 | Private mode: company text never leaves | Company text is read only by a local model; only guard-cleared keywords reach public research sources, and the user can preview them |

The merged learning, viewer, inbox, audit and SSO features are described in [docs/](docs/) (one page each).

## 4. Non-functional requirements

- **Security:** JWT auth, bcrypt passwords, ACL pre-filter in SQL, no chunk or question text in INFO logs, upload validation, rate limits, strict CORS.
- **Reproducibility:** `docker compose up` starts everything; `python -m app.seed` loads demo users and documents; tests run offline with fake models.
- **Performance:** p95 ≤ 4 s per question with a real model; ≥ 20 documents/min ingestion on a laptop with the fake embedder.
- **Observability:** per-stage latency, tokens and cost on every answer; Prometheus metrics.

## 5. Success metrics (on `backend/evals/golden.jsonl`)

| Metric | Target | Measured (fake models, default config) |
|---|---|---|
| Restricted questions refused | **100%** (CI gate) | 100% |
| Unanswerable questions refused | ≥ 90% | 90% |
| Recall@k | ≥ 0.85 | 1.00 |
| Faithfulness (verified / drafted claims) | ≥ 0.95 | 1.00 |
| Answerable questions refused wrongly | ≤ 10% | 3% |

## 6. Out of scope

Connectors (Drive, Confluence, SharePoint), multi-turn memory beyond the thread, fine-tuning embedding models. (OCR and SSO were out of scope at first; both now exist as optional features.)

## 7. Demo domain

A fictional handbook for "Acme Robotics": 16 general pages and 4 restricted HR documents ([corpus/README.md](corpus/README.md)). A second fictional company, Fernhollow Bicycle Works, is in [examples/](examples/README.md). Swap the corpus and golden set to change domain.
