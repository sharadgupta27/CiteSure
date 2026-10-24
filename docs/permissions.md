# Permissions: identities, scopes and why agents get no extra access

The core rule: **an agent is just another user.** It authenticates as an account, and the server's ACL decides what that account can read. There is no back door,
no database credential and no "admin mode" for tools.

## Identities

| Identity | Role | Reads | Can write | Used by |
|---|---|---|---|---|
| `employee@` (and any member) | workspace member | `workspace` collections | feedback, own threads | humans |
| `hr@` | member + group `hr` | + collections restricted to `hr` | same | humans |
| `admin@` | workspace admin | **every** collection in the workspace | collections, groups, members, documents, golden set, eval runs | humans |
| `agent@` (service user) | **plain member** | what `employee@` reads | only an answer-history entry (`ask`) | the MCP server |
| `eval-*@citesure.invalid` | synthetic members created by the evaluator | what their persona (plain member or group) may read | nothing; no usable password | the evaluator |
| GitHub workflow token | `issues: write`, `contents: read` | repository | issues/comments | the nightly agent |

Admins read all collections by design (they own the knowledge base). That makes admin credentials sensitive: never give one to an agent.
If you need to separate "manages the collection" from "reads the content", add a role that cannot read restricted collections; this is listed as a hardening idea in `security/threat-model.md`.

## MCP tools: what each needs

| Tool | HTTP calls | Needs | Reads content? | Writes | Notes |
|---|---|---|---|---|---|
| `list_collections` | `GET /workspaces/{id}/collections` | member | names only | no | only collections the user may read |
| `search_corpus` | `GET /retrieval/explain`, `GET /chunks/{id}` | member | yes (clipped to 1200 chars) | no | ACL-filtered by the API |
| `get_chunk` | `GET /chunks/{id}` | member | yes (clipped to 4000 chars) | no | 404 if not readable |
| `explain_retrieval` | `GET /retrieval/explain` | member | snippets (160 chars) | no | shows scores per stage |
| `ask` | `POST /ask` (always `scope: internal`) | member | yes (verified claims) | one `answers` row + a thread | rate limited (30/min); never searches the public internet, whatever `DEFAULT_SCOPE` is |
| `run_eval` | `POST /workspaces/{id}/eval-runs`, `GET /eval-runs/{id}` | **admin** | no | one `eval_runs` row | a plain-member agent gets 403: that is intended |
| resource `citesure://documents/{id}` | `GET /documents/{id}`, `/chunks` | member | yes (first 50 chunks, clipped) | no | |

There are **no** upload, delete, update or golden-set tools. Adding one requires updating this file and asking a human first (CLAUDE.md).

Verified live (see `docs/demo.md`): as `agent@`, `list_collections` shows only `General`; `explain_retrieval("severance salary bonus")` reports `allowed_collections: 1` and contains no confidential document;
`ask` for a restricted fact is refused; `run_eval` returns `403: Only workspace admins can do this`.

## Why an admin evaluation tool is optional

`run_eval` is useful for the `tune-retrieval` skill but needs an admin. Options, from safest to most convenient:

1. **Do not give the agent admin.** The human runs `uv run python -m app.evals.run` and pastes the table (default).
2. A **separate sandbox workspace** (a copy of the corpus with no confidential documents) where the agent's service user is admin. Nothing sensitive is reachable.
3. Never: an admin account in the production workspace.

## Agent runtime permissions (Claude Code `.claude/settings.json`)

- **allow** (no prompt): tests, linters, type-checks, `git status/diff/log`, and the read-only MCP tools.
- **ask**: `mcp__citesure__ask` and `run_eval` (they create records), `git commit/push`, `docker compose`, Alembic.
- **deny**: reading `.env*` and `corpus/raw/**`, force push, `rm -rf`, `aws`.
- **Hooks** are the enforcement layer behind those lists (a permission rule can be approved by a tired human; a hook cannot be talked into anything).
- The agent cannot loosen its own guardrails: edits to `agent-hooks/` and `.claude/settings.json` are blocked unless a human sets `CITESURE_HOOKS_UNLOCK=1`.

## Secrets

- The service user's password is read from `CITESURE_MCP_PASSWORD` in the agent's environment. It is never written to a file in the repository, never logged and never returned by a tool
  (a test asserts that error messages do not contain it or the JWT).
- Use a **long random password** for `agent@` in any shared environment (`AGENT_PASSWORD` for the seed); the demo password is for local use only.
- Tokens are short-lived JWTs held in memory; the client logs in again once on a 401.
- `httpx` request logging is turned off in the MCP server because request URLs contain question text.

## Data the agent may see

Agents (and the models behind them) receive chunk text and answers for documents the service user can read. That is *exactly* the data a human colleague with that account could read.
Do not point a hosted coding agent at a workspace whose documents your policy forbids sending to that vendor: see `security/ai-data-policy.md`.

**Private mode does not cover the agent.** The server keeps company text away from hosted *answer* models, but a coding agent that calls `ask` or `get_chunk` reads that text in its own vendor's model. In a private deployment give the agent no service account, or point it at a workspace that holds only non-sensitive documents.

## Prompt-injection stance for agents

Chunk text, answers and feedback comments are **untrusted data**. The subagents' instructions say so, they have no write tools, and the guard blocks the damaging actions
(secrets, golden edits, destructive commands, AWS) even if an instruction inside a document persuaded the model to try them.

## Change control

Adding a tool, widening a role, or giving the agent a new credential needs: an update to this file, a test that proves the new boundary, and a human review. The `api-contract-reviewer` subagent
checks API changes against the ACL rules; `docs/ai-workflow.md` records agent work for audit.
