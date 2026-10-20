# Chapter 7: Measuring RAG

*If you cannot measure it, you cannot improve it, and you will not notice it getting worse.*

**You will learn:** what to measure in a RAG system and why each number exists, how to run an experiment matrix, how to read the results honestly, and why a measuring tool needs its own tests.
**You will build:** an evaluation harness that asks the golden set through the real pipeline as different *people*, computes nine metrics, compares configurations, and gates CI.
**Time:** about 3 hours. **Code:** `backend/app/services/eval_runner.py`, `backend/app/evals/run.py`, `backend/evals/experiments.yaml`, `docs/eval-results.md`.

---

## The problem with "it looks good"

You try five questions. Four are fine. You ship. A month later someone tweaks how documents are split, and 8% of answers quietly get worse. Nobody notices until a customer does.

The cure is the golden set from chapter 1, plus a **harness** that runs it automatically and turns it into a handful of numbers. Then "I changed the chunk size" stops being an opinion and becomes *"MRR went from 0.98 to 0.97 and wrongful refusals tripled."*

## What to measure, in plain words

A RAG answer can fail at several stages, so we measure several stages. If you only measure "is the final answer right?", you will not know *where* to look when it is not.

| Stage | Metric | Plain-English meaning |
|---|---|---|
| Search | **recall@k** | Of the evidence we needed, how much was in the top k passages we handed to the model? |
| Search | **MRR** | How *high* did the right passage rank? (1st place = 1.0, 2nd = 0.5, 3rd = 0.33, averaged.) |
| Answer | **correctness** | Does the answer contain the same facts as the reference answer? (A judge decides.) |
| Answer | **faithfulness** | Of the claims the model wrote, what share survived verification? |
| Citations | **cite-precision** | Of the passages we cited, how many really contain the evidence? |
| Citations | **cite-recall** | Of the evidence that exists, how much did we cite? |
| Safety | **refusal accuracy** | Of the questions that *must* be refused, how many were? |
| Safety | **restricted refusal** | Same, for restricted questions only. **Must be exactly 100%.** |
| Cost of caution | **wrongful refusals** | Of the questions we *could* answer, how many did we refuse? (Lower is better.) |

The last row is the one people forget. You can get perfect safety by refusing everything. The two safety numbers and the wrongful-refusal number pull against each other, and the job is to find the right balance.

## Step 1: ask as different people

The harness does not ask all 40 questions as "the system". Each golden question says *who* is asking (`"ask_as": "hr"` or none). The harness creates a synthetic member for that persona, adds them to the right group, computes **their real permissions** with the same `allowed_collection_ids` function from chapter 3, and runs the real pipeline:

```python
allowed = await acl.allowed_collection_ids(session, personas[golden.ask_as], workspace_id)
async for kind, payload in run_pipeline(session, providers, settings,
        allowed_collection_ids=allowed, question=golden.question, config=config):
    ...
```

So when a restricted question is asked as a normal member, the test exercises the *real access rules*, not a simulation.

How does the harness know a retrieved chunk is "relevant" when chunk ids change every ingestion? It searches each chunk for the golden question's **expected quote** (chapter 1: quotes, not ids). That is also what makes experiments that change the chunk size possible.

## Step 2: the experiment matrix

An experiment is a row in a YAML file:

```yaml
experiments:
  - { name: vector-only,    retrieval_mode: vector, rerank: false }
  - { name: vector+rerank,  retrieval_mode: vector, rerank: true  }
  - { name: hybrid,         retrieval_mode: hybrid, rerank: false }
  - { name: hybrid+rerank,  retrieval_mode: hybrid, rerank: true  }
  - { name: hybrid+rerank/chunk-64,  chunk_tokens: 64  }
  - { name: hybrid+rerank/chunk-128, chunk_tokens: 128 }
```

Run it with one command (needs a Postgres, so `docker compose up -d db` first):

```bash
cd backend && uv run python -m app.evals.run --matrix evals/experiments.yaml --show-failures
```

Each distinct chunk size gets its own throw-away workspace (the demo corpus is ingested fresh), every configuration runs the 40 questions, and the throw-away data is deleted afterwards. It takes about 15 seconds.

## The results

![Results of the experiment matrix](images/fig-06-results.png)

| config | recall@6 | MRR | correct | faithful | cite-P | cite-R | refuse-acc | restricted | wrongly refused |
|---|---|---|---|---|---|---|---|---|---|
| vector only | 1.00 | 0.91 | 0.80 | 1.00 | 0.93 | 0.93 | 0.90 | 1.00 | 0.07 |
| vector + rerank | 1.00 | 0.98 | 0.80 | 1.00 | 0.91 | 0.97 | 0.90 | 1.00 | 0.03 |
| hybrid | 1.00 | 0.94 | 0.80 | 1.00 | 0.93 | 0.93 | 0.90 | 1.00 | 0.07 |
| **hybrid + rerank** | 1.00 | **0.98** | 0.80 | 1.00 | 0.91 | 0.97 | 0.90 | 1.00 | 0.03 |
| chunk 64 | 1.00 | 0.98 | 0.77 | 1.00 | 0.84 | 0.90 | 0.90 | 1.00 | 0.10 |
| chunk 128 | 1.00 | 0.97 | 0.80 | 1.00 | 0.88 | 0.93 | 0.90 | 1.00 | 0.07 |

**How to read it, as a story:**

1. **Reranking is the biggest win.** MRR 0.91 to 0.98, wrongful refusals 7% to 3%.
2. **Hybrid helps a little** (0.91 to 0.94).
3. **Recall is 1.00 everywhere: the corpus is too small to separate anything** (20 chunks, top 6 = 30% of everything). Pick metrics that can move.
4. **Smaller chunks are worse**: with 64-token chunks citation precision drops from 0.91 to 0.84 and wrongful refusals triple. A fact gets separated from its qualifiers.
5. **Restricted refusal is 1.00 in every row.** No setting answered a restricted question.

> The headline: *adding the reranker raised MRR from 0.91 to 0.98 and cut wrongful refusals from 7% to 3%, with restricted-question refusal unchanged at 100%.*

## Be honest about what the numbers are

These results use **fake providers** (a feature-hashing embedder, a lexical reranker and an extractive "LLM"). I say it at the top of the results file and in the README, because it changes what the numbers mean:

- They **do** tell you the plumbing works: retrieval, fusion, chunking, citation checking, access control, refusals. They are free, instant and *identical every run*, which is what lets CI use them as a gate.
- They **do not** tell you how a real language model or a real embedding model performs. That run happens nightly with real models (it needs an API key, and has not been run in the environment that built this guide).

A common mistake is to publish impressive numbers without saying what produced them. Do not.

## The knob: precision versus recall in miniature

The fake model answers only if its best sentence covers enough of the question's informative words (a setting called `FAKE_MIN_COVERAGE`). Sweeping it reproduces, in miniature, the main tuning problem in any RAG system:

| coverage required | correct | out-of-scope refused | wrongly refused | restricted refused |
|---|---|---|---|---|
| 0.30 | 0.80 | 0.90 | 0.03 | 1.00 |
| **0.40 (default)** | 0.80 | 0.90 | 0.03 | 1.00 |
| 0.50 | 0.65 | 1.00 | 0.27 | 1.00 |
| 0.60 | 0.58 | 1.00 | 0.33 | 1.00 |

Stricter means every out-of-scope question is refused, **but a quarter of answerable questions are refused too**. The restricted column never moves: access control happens *before* the model, so it does not depend on the model's judgement. That is what "enforce rules in code, not in prompts" buys you.

## Known failures, left visible

`docs/eval-results.md` lists the questions that still fail, and why. The most instructive: *"Who is the CEO of Acme Robotics?"* is **answered** with an unrelated but correctly cited sentence. All the checks passed (quote exists, sentence supports itself); it simply does not answer the question. That is the "verified is not relevant" limit from chapter 6, found by the 40-question set. A harness that hides its failures is decoration.

## The harness needed its own tests (three bugs)

Measuring tools can be wrong in ways that quietly mislead you. The evaluation found three bugs *in itself*:

1. **Random tie-breaking** made metrics change between identical runs (chapter 5). Fix: tie-break on stable keys; three runs now match exactly.
2. **A running worker stole the harness's work.** The first time I ran the matrix while the Docker `worker` container was also running, recall suddenly fell to 0.60 (from 1.00). Both the harness and the worker took jobs from the same queue table, but the worker could not see the harness's temporary files, so half the documents were never indexed. Fix: the seed script and the harness now ingest *inline* and do not use the shared queue. I knew something was wrong only because the number moved; without a baseline, I would have believed a bad result.
3. **Synthetic users showed up in the admin screen.** The evaluator's persona users (`…@citesure.invalid`) appeared in the member list and crashed the page (a validator refused to serialise a reserved `.invalid` address). It was caught by the browser test in chapter 9. Fix: system users are hidden from member and group lists, plus a regression test.

## Gate CI on it

Two scripts turn numbers into a decision:

- The harness itself exits with an error if `restricted_refusal_accuracy < 1.0`. **Never answering a restricted question is not a metric to trade off; it is a hard gate.**
- `backend/evals/check_regression.py` compares a run to the committed `baseline.json` and fails if any metric worsens by more than 0.02 (the golden set is small: differences below about 0.02 are noise).

```bash
python evals/check_regression.py eval-results.json evals/baseline.json --config hybrid+rerank
# ok   mrr   baseline=0.98 current=0.98 change=+0.00 ...
```

The GitHub workflow `rag-eval.yml` runs this on every pull request that touches the retrieval code, the services, the models, the evals or the corpus. A second job runs *nightly* with real models (when you add an API key) and opens an issue if something regressed (chapter 12).

## Recap

- Measure **each stage**: search, answer, citations, safety, and the *cost of caution* (wrongful refusals).
- Ask the golden set **as different people**, through the real access rules.
- An **experiment matrix** turns opinions into rows. Change one thing at a time.
- Say **what produced your numbers**. Keep the **failures** visible.
- Make safety a **hard gate**, quality a **regression check**, and **test your harness**.

## Try it yourself

1. Run the matrix and compare your table to mine. Are three consecutive runs identical?
2. Add an experiment with `top_k: 2`. Which metric moves first?
3. Add a golden question you expect to fail (use the `add-golden-question` skill's rules from chapter 12) and watch the metrics change.

**Next:** [Chapter 8: a UI people trust →](08-a-ui-people-trust.md)
