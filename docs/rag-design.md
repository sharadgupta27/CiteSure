# RAG Design: every decision and the evidence behind it

Numbers come from `docs/eval-results.md` (fake providers, deterministic, 40 golden questions). Where a decision rests on reasoning instead of an experiment, it says so.

## The pipeline

```text
question ─▶ ACL ─▶ embed ─▶ vector top-30 ┐
                          keyword top-30 ┴▶ RRF fuse ─▶ rerank (top 6) ─▶ generate (claims + quotes) ─▶ verify ─▶ answer | refusal
```

Every stage is a pure function with typed input and output (`list[ScoredChunk]`, `AnswerDraft`, `VerifiedAnswer`), composed by `services/pipeline.py` from a `PipelineConfig`. An experiment is therefore a configuration change, not a code fork.

## Decisions

| # | Decision | Alternatives | Evidence / reasoning |
|---|---|---|---|
| 1 | **Access control is a pre-filter inside the retrieval SQL** | filter after retrieval | Post-filtering leaks through scores, counts and timing, and can starve results (all top-k are restricted, nothing left to show). Tested by 17 leak tests and a truth-table unit test. Reasoning, not an experiment. |
| 2 | **pgvector inside the same Postgres** | separate vector DB | One database, ACL in the same SQL, one thing to back up and operate. HNSW index (`m=16`, `ef_construction=64`) with `hnsw.iterative_scan` so a restrictive filter still returns enough rows. |
| 3 | **Hybrid search (vector + Postgres full-text), fused with Reciprocal Rank Fusion** | vector only; weighted score sum | MRR 0.91 → 0.94 with hybrid. RRF needs no score normalisation (cosine similarity and `ts_rank_cd` live on different scales) and is easy to explain. Keyword search catches exact terms (ids, acronyms, numbers) that embeddings blur. The tsquery ORs the question's terms so a long natural-language question still matches. |
| 4 | **Cross-encoder style rerank of the top 30 → top 6** | no rerank | MRR 0.94 → 0.98 and wrongful refusals 7% → 3% (largest single gain). Cost is bounded because only 30 candidates are scored. Default offline stand-in: a lexical pair scorer; real: a `fastembed` cross-encoder. |
| 5 | **Heading-aware chunks, ~400 tokens, 15% overlap, never split a sentence, exact offsets** | fixed windows; semantic chunking | Offsets are what make the citation highlight correct (every chunk is an exact slice of the document text; unit-tested). Size sweep: 64 and 128 are worse on cite-P/cite-R; on this corpus 400 means one chunk per page. Overlap protects facts at borders. Long-document corpora need their own sweep. |
| 6 | **Chunks are embedded with title and heading path** | embed raw text | Reasoning (standard contextual-header trick): "Section 4.2" alone is meaningless. Not separately measured; it is the first stretch experiment. |
| 7 | **Answers are structured claims, each with a verbatim quote** | free text with `[1]` markers | Structure is what makes *deterministic* verification possible: a quote can be searched in the chunk. The model cites short ids (`S1`..), never database ids, so it cannot invent a valid chunk id. |
| 8 | **Two-stage verification: fuzzy quote match (>= 0.9) then LLM entailment** | LLM only; quote only | Stage 1 is free and catches fabricated quotes (tested with a hallucinating model). Stage 2 catches *real quote, wrong conclusion* (tested with a model that changes a number). Quotes shorter than 12 characters never count (a 3-letter quote matches anywhere). `partial` verdicts are dropped: nothing unverified reaches the user. |
| 9 | **Drop unsupported claims; refuse if none remain, with closest readable sources** | show with a warning | The product promise is "every sentence is verified". A refusal that still points to the nearest documents is useful. `answerable_refusal_rate` tracks the cost of strictness. |
| 10 | **Document text is untrusted**: delimited, id-tagged sources; forged tags neutralised; no tools for the generation or verification model | trust the prompt | Writing the injection test found a real gap (a forged `<system>` tag passed through). See `security/threat-model.md` T1. |
| 11 | **Only verified text is streamed** | stream tokens as generated | Streaming unverified text and retracting it later would put wrong content in front of the user. The stage events (`retrieving`, `generating`, `verifying`) keep the wait understandable. |
| 12 | **Evaluation is part of the product**: golden set first, metrics per stage, persona-based, hard gate on restricted refusals | spot checks | Phase 0 wrote 40 questions before any RAG code. The harness found three of its own bugs (`eval-results.md`). Golden questions store *quotes*, not chunk ids, so they survive any re-chunking. |
| 13 | **Postgres job queue (`FOR UPDATE SKIP LOCKED`)** | Redis + Celery | One less service; at-least-once delivery with retries and backoff; stuck jobs are recovered after 15 minutes. Tested with 8 concurrent claimers. |
| 14 | **Local embeddings by default (fastembed, 384 dims)** | hosted embeddings | Free, no data leaves the machine, works in CI. The column is `VECTOR(384)`: a model with another dimension needs a migration and a full reindex (a Voyage model returning another size is refused at startup). |
| 15 | **Fake providers everywhere in tests** | call a real LLM | Deterministic, free, offline. Real-model quality is checked nightly. |

## What is deliberately not done (and what it would take)

| Gap | Why it matters | Next step |
|---|---|---|
| Answers are verified for *support*, not *relevance* | the CEO and "office days" cases in `eval-results.md` | add a third stage: does the claim answer the question? (LLM judge on question + claim), measured by a new `answer_relevance` metric |
| No semantic embeddings in the measured results | the hybrid gain will change with a real model | nightly real-model run; compare `EMBEDDING_MODEL` options |
| 40 questions, 20 pages | differences under 0.02 are noise | fetch the GitLab handbook (`corpus/fetch_gitlab_handbook.py`) and grow the golden set |
| Multi-turn follow-ups are not rewritten into standalone queries | "and for adoption?" fails | query rewriting with the thread history (stretch goal) |
| Scanned PDFs (no OCR) | upload fails with a clear message | optional OCR step in the worker |

## Parsing and ingestion

| Type | Parser | Notes |
|---|---|---|
| Markdown | `markdown-it-py` | headings -> heading paths; list items and table rows become their own lines; raw HTML tags are dropped |
| HTML | `beautifulsoup4` | scripts, styles, nav and footers removed; leaf blocks only so nested lists are not duplicated |
| DOCX | `python-docx` | heading styles -> heading paths; tables in reading order; merged cells de-duplicated |
| PDF | `pypdf` | one section per page with page numbers (so citations can say "p. 3"); soft line wraps and hyphenation repaired; scanned PDFs fail with a clear message |

Throughput, **measured** on a Windows laptop with the fake embedder (`python -m app.seed` prints it): 20 documents in 0.6 s, about 1,900 documents/minute (documents are short: one chunk each). With a real embedding model the embedding step dominates (the worker batches 64 chunks per call); measure with `WITH_ML=true`.
The upload path never parses: it validates (magic bytes, size, zip-bomb limits, duplicate sha256), stores the blob and queues a job; the worker moves the document through `queued → parsing → embedding → ready` and the UI polls.
