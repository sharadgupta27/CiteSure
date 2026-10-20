# CiteSure — Product Spec

> Answers you can verify. Grounded document Q&A with checked citations and permission-aware retrieval.

## 1. Problem

Employees lose hours searching policy documents, handbooks and manuals. Generic chatbots answer confidently but cannot show *where* an answer came from, so nobody trusts them for HR, compliance or security questions. Many internal RAG systems also leak documents across permission boundaries: a chatbot that can read the confidential folder will happily summarize it for anyone.

CiteSure fixes both problems:

1. **Every sentence carries a citation** (document, section/page, and the quoted words).
2. **Every citation is verified** before the user sees it. Claims the sources don't support are dropped. If nothing is supported, the system says *"I don't have information on that"*.
3. **Access control lives inside retrieval.** Chunks from collections a user may not read are never fetched, so they can't leak into an answer, a count or a timing signal.

## 2. Personas

| Persona | Goal | Pain today |
|---|---|---|
| **Employee (Eva)** | Get a trustworthy answer to "how many days of parental leave do I get?" in seconds | Searching a wiki, then asking HR anyway; chatbots she can't trust |
| **Knowledge-base admin (Adam)** | Own the documents, the access rules and the answer quality | No way to know whether the bot is right, or whether it leaks |
| **HR member (Hana)** | Read confidential People-Ops documents with the same tool | Confidential docs are in a separate system nobody searches |
| **Coding agent (service user)** | Diagnose a bad answer by inspecting retrieval | Agents with raw DB access see everything |

## 3. User stories and acceptance criteria

### Documents and access

| # | Story | Acceptance criteria |
|---|---|---|
| D1 | As an admin I create a workspace with collections and groups | A collection has `visibility = workspace` (all members) or `groups` (listed groups only). Workspace admins can read every collection. |
| D2 | As an admin I upload PDF, DOCX, Markdown and HTML documents | File type is checked by **magic bytes** (not the filename); max 20 MB; a duplicate (same sha256) in the same collection is rejected with 409; status moves `queued → parsing → embedding → ready` (or `failed` with an error) and the UI shows it. |
| D3 | As an admin I delete a document | The document, its chunks, embeddings and stored file are removed. |
| D4 | As an admin I can reindex a document | A new ingestion job is queued; old chunks are replaced atomically. |

### Asking questions

| # | Story | Acceptance criteria |
|---|---|---|
| Q1 | As an employee I ask a question and get an answer | The answer is a list of claims; each claim has ≥ 1 citation with a quoted span from a retrieved chunk. |
| Q2 | I can verify a citation | Clicking a citation opens the source with the quoted span highlighted. |
| Q3 | I never see an unverified claim | Each claim passed *quote match* (≥ 0.9 fuzzy match) **and** *entailment*. Others are dropped. |
| Q4 | If the documents don't answer the question, the system says so | Status `refused`, message "I don't have information on that", plus links to the closest sources I may read. |
| Q5 | I can't read what I'm not allowed to read | A question that only a restricted collection could answer is refused. Restricted chunk text never appears in an answer, a citation, `/chunks/{id}`, `/documents/{id}/file` or `/retrieval/explain`. |
| Q6 | I see progress while waiting | `/ask/stream` emits `stage` events (`retrieving`, `generating`, `verifying`) then the final answer. |
| Q7 | A poisoned document can't hijack the system | Instructions inside documents ("ignore previous instructions…") are treated as data and never change behavior. |

### Feedback and quality

| # | Story | Acceptance criteria |
|---|---|---|
| F1 | As an employee I give a thumbs up/down with a comment | Stored with the answer id and my user id. |
| F2 | As an admin I review feedback and promote it to the golden set | Promotion creates a golden question (source = `feedback`) with a stated reason. |
| E1 | As an admin I run the evaluation suite | Runs in the worker; reports recall@k, MRR, faithfulness, citation precision/recall, refusal accuracy. |
| E2 | I compare two configurations | Compare view shows metrics side by side with deltas. |
| E3 | The admin dashboard shows quality over time | One row per eval run with the config used. |

## 4. Non-functional requirements

- **Security:** JWT auth; passwords hashed (bcrypt); ACL pre-filter in SQL; no chunk text or question text in INFO logs; upload validation; rate limiting; strict CORS.
- **Reproducibility:** `docker compose up` starts everything; `python -m app.seed` loads the demo corpus and demo users; tests run offline (fake LLM and embedder).
- **Performance:** target p95 ≤ 4 s per question with the real LLM; ingestion ≥ 20 documents/min on a laptop with the fake embedder.
- **Observability:** per-stage latency, token and cost capture in every answer; Prometheus metrics at `/metrics`.

## 5. Non-goals (MVP)

Connectors (Drive/Confluence/SharePoint), multi-turn memory beyond the thread, OCR for scanned PDFs, SSO/SAML, fine-tuning embedding models.

## 6. Success metrics (measured on `backend/evals/golden.jsonl`)

| Metric | Target |
|---|---|
| Refusal accuracy on restricted questions | **100 %** (hard gate in CI) |
| Refusal accuracy on all unanswerable questions | ≥ 90 % |
| Recall@5 | ≥ 0.85 |
| Faithfulness (verified claims / drafted claims) | ≥ 0.95 |
| Answerable questions refused wrongly | ≤ 10 % |

## 7. Demo domain

A fictional company handbook ("Acme Robotics"): 16 public policy pages and 4 restricted HR documents. See `corpus/README.md`. The pipeline is domain-agnostic: swap the corpus and the golden set.
