# CiteSure MCP server

A small [Model Context Protocol](https://modelcontextprotocol.io) server that lets a coding agent diagnose CiteSure answers using **scoped tools instead of database access**.
It logs in as a service user and calls the normal API, so the same access rules that protect human users protect the agent.

| Tool | Purpose | Needs |
|---|---|---|
| `list_collections` | collections the service user may read | member |
| `search_corpus(query, limit)` | top chunks with text (clipped) | member |
| `get_chunk(chunk_id)` | one chunk with location | member |
| `explain_retrieval(query, retrieval_mode, rerank)` | candidates and scores at every retrieval stage | member |
| `ask(question)` | ask like a user; verified claims or refusal, dropped-claim count | member |
| `run_eval(name, retrieval_mode, rerank, top_k)` | run the golden set, return metrics | **admin** (a member gets a clear 403) |

Resource: `citesure://documents/{document_id}`. Prompt: `diagnose-bad-answer`. No write or delete tools exist. Full matrix: [docs/permissions.md](../docs/permissions.md).

## Setup

1. Start CiteSure and seed it (`docker compose up -d --build && docker compose run --rm api python -m app.seed`). The seed creates `agent@acme.example` as a **plain member**.
2. Give the server its credentials through the environment (never a committed file):

```bash
export CITESURE_URL=http://localhost:8000
export CITESURE_MCP_EMAIL=agent@acme.example
export CITESURE_MCP_PASSWORD=citesure-demo        # local demo only; use a random password elsewhere
# optional: CITESURE_WORKSPACE_ID=<uuid>          # default: the user's first workspace
```

3. Register it. In this repository `.mcp.json` already does:

```json
{ "mcpServers": { "citesure": { "command": "uv", "args": ["run", "--project", "mcp-server", "--quiet", "python", "mcp-server/server.py"] } } }
```

For Claude Code: `claude mcp add citesure -- uv run --project mcp-server python mcp-server/server.py`. For other clients, use the same command as a stdio server (see `docs/course/` client notes).

## Try it without an agent

```bash
cd mcp-server
uv run python - <<'PY'
import asyncio, server
print(asyncio.run(server.explain_retrieval("How many weeks of parental leave?")))
PY
```

## Tests

`uv run pytest -q` (12 tests, mocked API, no network). They cover: tool registration (no write/delete tools), read-only annotations, ACL-shaped errors, output clipping,
secrets never appearing in errors, re-login on token expiry, and a permission error for `run_eval` as a member.

## Design notes

- Output is **clipped** (1200 chars per chunk in search results) so a tool cannot be used to dump a corpus into a model context.
- Errors are returned as `ERROR: ...` strings so the agent can reason about them; they never include tokens or passwords.
- `httpx` request logging is disabled because URLs contain question text (privacy rule: no question text in logs).
- The MCP SDK is v2 (`MCPServer`); if you pin `mcp<2` use `FastMCP` from `mcp.server.fastmcp` instead.
