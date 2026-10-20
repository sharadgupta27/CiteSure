# Agent demo: from "that answer is wrong" to a reviewed fix

This is the Module 5 demo script ([requirements](course/module5-requirements.md)) played on a **real** wrong answer from this system.
Outputs marked **captured** were produced by the running stack. Parts that need a live Claude Code session (the agent choosing skills and spawning subagents)
are described as the expected behaviour; they were not recorded in the session that built this repository, and are marked **to rehearse**.

## The bug report

> **User:** I asked "Which days of the week am I expected to be in the office?" and CiteSure told me about core hours. It even shows a citation!

Setup: `docker compose up -d --build && docker compose run --rm api python -m app.seed`, then start the agent in the repo with `CITESURE_MCP_PASSWORD` set.

## 1. The agent reads the project instructions

Claude Code loads `CLAUDE.md` (and `AGENTS.md`). It now knows the four non-negotiables, the commands, and that it must not edit the golden set.
**To rehearse:** ask "What must you never do in this repo?" and check the answer lists ACL, verification, untrusted text and the golden set.

## 2. A reusable workflow is invoked

The agent recognises "answer is wrong" and loads the `add-golden-question` skill, whose first step is *reproduce*.

## 3. A specialist subagent investigates (and calls MCP tools)

The skill hands diagnosis to **`retrieval-debugger`** (read-only; tools limited to the MCP server). Its calls and the **captured** results:

```text
ask("Which days of the week am I expected to be in the office?")
  status: answered, dropped_claims: 0
  claim: "Everyone is expected to be reachable during core hours, which are 10:00 to 15:00 in your l..."
  cites: Remote and Hybrid Work | verification: quote_match 1.0, entailment supported

explain_retrieval(same question)
  reranked rank 1  1.05  Remote and Hybrid Work   "Acme Robotics follows a hybrid model. Employees in roles that do not n..."
  reranked rank 2  0.53  On-Call Rotation
  reranked rank 3  0.53  Onboarding Guide
  vector rank of "Remote and Hybrid Work": 1      keyword (FTS) rank: 4

search_corpus("office Tuesdays Thursdays", limit=1)
  Remote and Hybrid Work  -> the chunk text contains "Tuesdays and Thursdays"
```

The debugger's report (format fixed by its instructions; **the conclusion below follows from the captured evidence**):

```text
FAILING STAGE: generation
EVIDENCE
- explain_retrieval: the chunk that contains "come to the office on Tuesdays and Thursdays" is rank 1 after rerank. Retrieval and rerank are fine.
- ask: the answer cites that same chunk, but quotes the core-hours sentence. The claim is real, quoted exactly and judged supported.
PROPOSED FIX: the generator chose a related but wrong sentence. (In this offline demo the generator is the deterministic fake, a bag-of-words
              sentence picker; with a real model this question is answered correctly. The process is identical when the failing stage is chunking.)
HOW TO PROVE IT: add a golden question for this phrasing; metric to watch: `correctness`.
```

Two lessons worth saying out loud:

1. **Verified is not the same as relevant.** Verification proves a claim is supported by its quote. It does not prove the claim answers the question. That is why the evaluation also measures `correctness`, and why `docs/rag-design.md` lists an answer-relevance check as the next improvement.
2. **The agent found this without touching the database**, using the same access rules as an employee.

## 4. The MCP server enforces access even for the agent

**Captured**, with the agent running as the plain-member service user `agent@acme.example`:

```text
list_collections      -> [General]                                   (People-Ops-Confidential is invisible)
explain_retrieval("severance salary bonus")
                      -> allowed_collections: 1, no confidential document in any stage
ask("What is the maximum severance in weeks?")
                      -> refused: "I don't have information on that in the documents available to you."
run_eval("agent-check")
                      -> ERROR: ... failed with HTTP 403: Only workspace admins can do this
```

## 5. A guardrail stops a shortcut

The tempting wrong move: make the failing metric pass by changing the golden answer. **Captured** output of the real hook (`agent-hooks/guard.py`) for each attempt:

```text
Edit backend/evals/golden.jsonl
BLOCKED by CiteSure guardrail: .../backend/evals/golden.jsonl is the golden evaluation set (no approval recorded). Never edit it to make
metrics pass. Follow the add-golden-question skill: it proves the new question fails today, records the reason with
`python agent-hooks/approve_golden_change.py "<reason>"`, and only APPENDS entries.          (exit code 2)

Bash: sed -i s/16/8/ backend/evals/golden.jsonl
BLOCKED by CiteSure guardrail: writing the golden set from the shell is not allowed without explicit human approval. Ask the user.   (exit code 2)

Read .env
BLOCKED by CiteSure guardrail: .../.env may contain secrets. Document variables in .env.example instead.                              (exit code 2)
```

The message tells the agent the **sanctioned path**, so a blocked agent does the right thing instead of looping.

## 6. The correct fix path, and the human reviews the diff

The skill continues:

1. Write the new line (the exact supporting sentence is copied verbatim from `corpus/demo/general/remote-work.md`):
   ```json
   {"id":"g41","question":"On which days of the week should I come to the office?","expected_answer":"Tuesdays and Thursdays.","expected_quotes":[{"document":"remote-work.md","quote":"come to the office on Tuesdays and Thursdays"}],"answerable":true,"ask_as":null,"tags":["bug","remote-work"],"reason":"User reported core-hours sentence returned for an office-days question (verified but not relevant)"}
   ```
2. `python corpus/validate_golden.py` (checks the quote exists) and the evaluation (`--show-failures`) to **prove it fails today**.
3. `python agent-hooks/approve_golden_change.py "<reason>"` then **append** the line. `check_golden_append_only.py` confirms nothing existing changed.
4. The Stop hook runs the golden checks and the backend unit tests (including the ACL rule tests) before the agent may say "done".
5. **The human reviews the diff**: one added JSONL line with a reason, and (when a fix exists) a small change with before/after numbers from `tune-retrieval` in `docs/eval-results.md`.

## Why this demo is convincing

- The bug is real, not staged: it comes from the system's own evaluation output.
- Every claim about access control was checked against a running server, as a low-privilege user.
- The guardrail outputs are the hooks' actual stderr, and the hooks have their own tests (`python -m pytest agent-hooks/tests`).
- The whole thing leaves an audit trail: `agent-hooks/logs/audit.jsonl` (decisions, no contents) and `docs/ai-workflow.md`.

## Parallel work (optional second act, to rehearse)

Two subagents in separate worktrees: one adds a DOCX table parser (`backend/app/rag/parsing/docx.py` and tests), the other fixes a frontend citation-viewer bug
(`frontend/src/components/SourceViewer.tsx` and tests). Disjoint files, so the main session merges two small reviewed diffs. See `docs/agent-extension-pack.md`.
