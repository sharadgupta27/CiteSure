# Evaluation Results

> **Read this first.** These numbers were produced with the **deterministic fake providers** (a feature-hashing embedder, a lexical reranker, and an extractive "LLM"). They measure the *plumbing*
> (retrieval, fusion, reranking, chunking, citation verification, access control, refusals) and they are reproducible and free. They do **not** measure the quality of a real LLM or a real
> embedding model: that run happens nightly with real models (`.github/workflows/rag-eval.yml`, needs `ANTHROPIC_API_KEY`) and has not been run in the environment that produced this file.

Reproduce everything: `cd backend && uv run python -m app.evals.run --matrix evals/experiments.yaml` (needs Postgres: `docker compose up -d db`). Three consecutive runs give identical numbers.

## The setup

- Corpus: 20 pages of a fictional handbook (16 public, 4 HR-only). Golden set: **40 questions** (`backend/evals/golden.jsonl`): 25 answerable by anyone, 5 answerable only by `hr`, 5 out of scope, 5 restricted (the answer exists, but the asker may not read it).
- Questions are asked as **personas** (a plain member, or a member of the `hr` group) through the real pipeline, so the access rules are exercised for real.
- Each metric, in plain words:

| Metric | Meaning | Good is |
|---|---|---|
| `recall@k` | share of expected evidence found in the top k chunks given to the model (k = 6) | high |
| `MRR` | 1 / rank of the first relevant chunk, averaged: *how high* the right chunk is | high |
| `correct` | judge says the answer has the same facts as the reference | high |
| `faithful` | verified claims / drafted claims (how much of what the model wrote survived verification) | high |
| `cite-P` | cited chunks that contain expected evidence / all cited chunks | high |
| `cite-R` | expected evidence that was actually cited | high |
| `refuse-acc` | out-of-scope and restricted questions that were refused | high |
| `restricted` | restricted questions refused (**must be 1.00**, a hard CI gate) | exactly 1.00 |
| `wrong-refusal` | answerable questions that were refused | **low** |

## Results: the experiment matrix

| config | recall@k | MRR | correct | faithful | cite-P | cite-R | refuse-acc | restricted | wrong-refusal |
|---|---|---|---|---|---|---|---|---|---|
| vector-only | 1.00 | 0.91 | 0.80 | 1.00 | 0.93 | 0.93 | 0.90 | 1.00 | 0.07 |
| vector + rerank | 1.00 | 0.98 | 0.80 | 1.00 | 0.91 | 0.97 | 0.90 | 1.00 | 0.03 |
| hybrid (vector + keyword) | 1.00 | 0.94 | 0.80 | 1.00 | 0.93 | 0.93 | 0.90 | 1.00 | 0.07 |
| **hybrid + rerank (default)** | 1.00 | **0.98** | 0.80 | 1.00 | 0.91 | 0.97 | 0.90 | 1.00 | 0.03 |
| hybrid + rerank, chunk 64 | 1.00 | 0.98 | 0.77 | 1.00 | 0.84 | 0.90 | 0.90 | 1.00 | 0.10 |
| hybrid + rerank, chunk 128 | 1.00 | 0.97 | 0.80 | 1.00 | 0.88 | 0.93 | 0.90 | 1.00 | 0.07 |

### What the numbers say

1. **Reranking is the biggest win: MRR 0.91 → 0.98 (+0.07)**, and wrongful refusals fall from 7% to 3%. Reading the question and passage *together* puts the right chunk first more often than comparing two separate vectors.
2. **Hybrid search helps a little: MRR 0.91 → 0.94 (+0.03).** The keyword half catches exact terms the (deliberately lexical, non-semantic) fake embedder blurs. With a real embedding model the vector half is much stronger, so expect a different split; the nightly real-model run will show it.
3. **`recall@6` is 1.00 for every setting: the corpus is too small to separate them.** With 20 chunks, the top 6 is 30% of everything. *MRR* is the metric that discriminates here. (Lesson: pick metrics that can move on your data.)
4. **Smaller chunks are worse here.** With 64-token chunks cite-P falls 0.91 → 0.84, cite-R 0.97 → 0.90 and wrongful refusals triple (0.03 → 0.10): a fact and the words that qualify it get split across chunks. The default (400 tokens, which for these short pages means *one chunk per page*) stays. Chunk sizes 256 and 800 from the plan are not in the table because every page is already shorter than 256 tokens, so they would be identical to 400; on a corpus of long documents run `256/400/800` (edit `evals/experiments.yaml`).
5. **Faithfulness is 1.00 and restricted refusal is 1.00 in every row.** The first is by design (only verified claims are returned, so the share that survives is measured on the *drafted* claims, which the fake model does not invent). The second is the product promise: no setting, however aggressive, answered a restricted question.

### Before / after the change that mattered

> Adding the reranker to vector search raised MRR from **0.91 to 0.98** and cut wrongful refusals from **7% to 3%**, with restricted-question refusal unchanged at **100%**.

## The fake LLM's precision / recall knob

The extractive fake answers only when its best sentence covers enough of the question's informative words (`FAKE_MIN_COVERAGE`). Sweeping it is a miniature of the real tuning problem
(*verification too strict -> refuses answerable questions; too loose -> answers what it should not*):

| `FAKE_MIN_COVERAGE` | correct | refuse-acc | wrong-refusal | restricted |
|---|---|---|---|---|
| 0.30 | 0.80 | 0.90 | 0.03 | 1.00 |
| **0.40 (default)** | 0.80 | 0.90 | 0.03 | 1.00 |
| 0.50 | 0.65 | 1.00 | 0.27 | 1.00 |
| 0.60 | 0.58 | 1.00 | 0.33 | 1.00 |

At 0.50+ every out-of-scope question is refused, but a quarter of answerable ones are too. The default keeps wrongful refusals at 3% and accepts one out-of-scope miss (below).
`restricted` stays at 1.00 across the whole sweep because access control is enforced before the model sees anything, not by the model's judgement.

## Known failures (deliberately not hidden)

| Question | What happened | Why |
|---|---|---|
| "Who is the CEO of Acme Robotics?" (out of scope) | **Answered** with an unrelated, *correctly cited* sentence ("Acme Robotics observes 10 paid holidays…") | **Verified is not the same as relevant.** The quote is real and supports its own sentence, but the sentence does not answer the question. A real LLM refuses here; the fake cannot. An answer-relevance check is the next planned stage (`docs/rag-design.md`, `security/threat-model.md` T15). |
| "Which days of the week am I expected to be in the office?" | Cites the right page but returns the *core hours* sentence | The fake picks the wrong sentence inside the right chunk (retrieval is fine: rank 1). Used as the real bug in `docs/demo.md`. |
| "Who has to approve an expense of $3,000?", "How is severance calculated?" and a few others | Counted "partial" by the judge | They need range reasoning or multi-sentence answers; the extractive fake returns one sentence. Tagged `reasoning` in the golden set. |

## Three bugs the evaluation found in its own harness

These are in the log because they are the best argument for measuring: each would have silently corrupted conclusions.

1. **Random tie-breaking made metrics change between identical runs** (hybrid MRR 0.94 vs 0.91). Chunk ids are random per ingestion, and ties were broken on them. Fix: tie-break on (document, position); regression test added; three runs now match exactly.
2. **A running worker stole the evaluation's ingestion jobs** (recall collapsed to 0.60). The CLI used the shared job queue while the Compose worker also consumed it, but the worker could not see the CLI's temporary files. Fix: seeding and evaluation ingest inline.
3. **A persona crash in the admin UI.** Synthetic evaluation users (`…@citesure.invalid`) showed up in the member list and made `GET /members` return 500. Found by the end-to-end test. Fix: system users are hidden from member and group lists; regression test added.

## Limits

- 40 questions: differences under about 0.02 are noise. CI fails a change only if a metric drops by more than 0.02 from `backend/evals/baseline.json`, or if any restricted question is answered.
- Fake providers: see the box at the top. A real-model run, a larger corpus (the GitLab handbook fetch script is in `corpus/`) and a held-out question set are the next steps before claiming real-world quality.
