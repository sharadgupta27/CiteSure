# Agent Extension Pack

This is the Module 5 deliverable: everything needed so a coding agent can work **on** CiteSure, and **with** CiteSure, safely.
Requirements: [docs/course/module5-requirements.md](course/module5-requirements.md). Security model: [permissions.md](permissions.md). Walkthrough: [demo.md](demo.md).

## The mental model

```text
instructions      what the agent must know and must never do            AGENTS.md, CLAUDE.md
context           what it reads before acting                           plan.md, product-spec.md, openapi.yaml
tools             what it can call                                      MCP server (6 scoped tools)
permissions       what it may do without asking                         .claude/settings.json + the service user's ACL
reusable flows    procedures we keep repeating                          4 skills
specialist agents isolated context, narrower permissions               3 subagents
guardrails        rules enforced by code, not by "please be careful"    hooks (guard, format, stop)
packaging         share it across projects and teams                    plugin
custom agents     scheduled, unattended work                            nightly regression agent
audit trail       what happened, afterwards                             agent-hooks/logs/audit.jsonl + docs/ai-workflow.md
```

The names differ per tool (a "skill" is a command, rule, recipe or prompt elsewhere). The capability is what matters.

## What is in the pack

| Requirement (minimum) | Delivered | Where |
|---|---|---|
| 1 project instructions file | `AGENTS.md` (portable) + `CLAUDE.md` (Claude Code detail) with non-negotiables, commands, boundaries | repo root |
| 1 reusable workflow | **4 skills**: `add-golden-question`, `ingest-new-doc-type`, `tune-retrieval`, `review-api-change` | `agent-capabilities/` |
| 1 specialized subagent | **3 subagents**: `retrieval-debugger`, `citation-auditor`, `api-contract-reviewer` (all read-only) | `agent-capabilities/subagents/` |
| 1 MCP tool/server | **MCP server**: 6 tools, 1 resource, 1 prompt, runs as a scoped service user | `mcp-server/` |
| 1 hook or guardrail | **3 hooks** + a golden-set append-only check; 60 tests | `agent-hooks/` |
| plugin OR custom agent | **both**: a plugin bundling all of the above, and a nightly regression agent | `plugins/citesure-agent-pack/`, `custom-agent/` |
| 1 permission/security note | [permissions.md](permissions.md), plus the threat model in `security/` | `docs/` |

## Instructions: `AGENTS.md` and `CLAUDE.md`

`AGENTS.md` is the portable core that Codex, Cursor, Copilot and others read. `CLAUDE.md` adds workflow rules specific to Claude Code (one task at a time, ask-before lists,
log AI usage). Both state the **four non-negotiables** (ACL inside retrieval SQL, no unverified claim reaches a user, document text is untrusted, never edit the golden set to pass)
and point at the commands. Instructions are *advice*; the hooks below make the most important ones *rules*.

## Skills (reusable workflows)

| Skill | Trigger | Output | Why it is a skill |
|---|---|---|---|
| `add-golden-question` | "this answer is wrong", a feedback entry | one new golden line that provably fails today | the 7-step procedure (reproduce, evidence, append, validate, prove, approve, report) is easy to skip steps in |
| `tune-retrieval` | low recall/MRR, a failing question | before/after table, one change at a time | stops "looks better" changes; encodes the metric rules |
| `ingest-new-doc-type` | "support PPTX" | detection + parser + fixtures + tests + eval | touches 6 places; a checklist prevents missing one |
| `review-api-change` | any `openapi.yaml` change | contract-first change + independent review | contract, client, backend and ACL tests must move together |

## Subagents (specialists with isolated context)

All three are **read-only**: their `tools:` lists contain no Edit/Write (a test asserts this).

- **`retrieval-debugger`** uses the MCP tools to find *which stage* lost a fact (parsing, chunking, retrieval, rerank, generation, verification, or access control).
- **`citation-auditor`** samples answers and checks every citation supports its claim: the human-facing check on the "verified" badge.
- **`api-contract-reviewer`** reviews diffs for compatibility and, above all, for ACL coverage on content-returning endpoints.

Why subagents: each investigation reads lots of chunk text and tool output. In a separate context that noise never pollutes the main session, and the narrow tool list limits damage if a document contains an injected instruction.

## MCP server

Six tools (`list_collections`, `search_corpus`, `get_chunk`, `explain_retrieval`, `ask`, `run_eval`), one resource (`citesure://documents/{id}`) and one prompt (`diagnose-bad-answer`).
It logs in as a **plain-member service user** and calls the normal HTTP API, so the same ACL that protects humans protects the agent. No write or delete tools exist.
Details and the tool-by-tool permission table: [permissions.md](permissions.md). Setup: [../mcp-server/README.md](../mcp-server/README.md).

## Hooks (guardrails enforced by code)

| Hook | Event | What it does |
|---|---|---|
| `guard.py` | PreToolUse | blocks `.env*` and `corpus/raw/`, edits to `golden*.jsonl` without a reasoned approval, edits to committed migrations and the generated client, destructive shell commands, AWS/deploy commands, shell tricks that write the golden set, and edits to the guardrails themselves |
| `format_on_save.py` | PostToolUse | ruff (Python) or eslint (TypeScript) on the file just written; remaining problems go back to the agent |
| `stop_tests.py` | Stop | runs golden-set checks, backend unit tests (including the ACL rule tests) and, if the frontend changed, typecheck and unit tests; blocks "done" while red |
| `check_golden_append_only.py` | Stop, CI | fails if an existing golden question was deleted, weakened or rewritten without a new reason |

Everything is audited to `agent-hooks/logs/audit.jsonl` (targets and decisions only, never file contents).
The hooks are tested by running them as real subprocesses with the same JSON protocol the agent uses: `python -m pytest agent-hooks/tests` (60 tests).
One test exists because the first version **failed open**: a path the guard could not make relative to the project root slipped through. Rules now match on the path's tail at any depth.

## Plugin

`plugins/citesure-agent-pack/` bundles skills, subagents, hooks and the MCP config. The canonical files stay in `agent-capabilities/`, `agent-hooks/` and `mcp-server/`;
`python agent-hooks/install.py` syncs the copies and `--check` (a test and a CI job) fails on drift. Install: see the plugin README.

## Custom agent

`custom-agent/agent.py` is the nightly regression watcher: it diffs tonight's evaluation against the previous run and opens **one** issue with suspected causes.
See [../custom-agent/README.md](../custom-agent/README.md).

### When to build a custom agent instead of using an interactive one

| Use an interactive coding agent when... | Build a custom agent when... |
|---|---|
| a human is present to steer and approve | it runs unattended on a schedule or in CI |
| the task is open-ended (explore, design, refactor) | the task is a fixed pipeline with one clear output |
| you want maximum flexibility | you want reproducibility, tiny permissions and low cost |
| a wrong step is cheap to notice and undo | a wrong step must be impossible (only an issue can be written) |

## Parallel work with worktrees

Two subagents can work at the same time if they cannot touch the same files:

```bash
git worktree add ../citesure-docx-tables -b feat/docx-tables       # agent A: DOCX table parser (backend/app/rag/parsing/docx.py + tests)
git worktree add ../citesure-viewer-fix  -b fix/citation-highlight  # agent B: citation viewer fix (frontend/src/components/SourceViewer.tsx + tests)
```

The main session is the orchestrator: it writes each agent a task with the files it owns, the tests that must pass and what it must not touch, then reviews two small diffs
and merges them one at a time (the hooks and CI run in each worktree). Disjoint file ownership is what makes this safe.

## Using the pack with other tools

| Capability | Claude Code | Others |
|---|---|---|
| instructions | `CLAUDE.md` | `AGENTS.md` (Codex, Cursor, Copilot, OpenCode, Aider) |
| skills | `.claude/skills/*/SKILL.md` | paste as rules/commands/prompts; they are plain Markdown procedures |
| subagents | `.claude/agents/*.md` | custom modes or sub-tasks with the same tool restrictions |
| MCP | `.mcp.json` | any MCP client (see `docs/course/` client notes) |
| hooks | `.claude/settings.json` | scripts are generic: JSON on stdin, exit 2 blocks; wire them to your tool's hook/pre-commit mechanism |
