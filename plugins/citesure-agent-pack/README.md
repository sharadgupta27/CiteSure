# citesure-agent-pack

A shareable Claude Code plugin that bundles everything an agent needs to work safely on CiteSure (or on a RAG project built the same way).

| Part | Where | What it does |
|---|---|---|
| Skills | `skills/` | `add-golden-question`, `ingest-new-doc-type`, `tune-retrieval`, `review-api-change` |
| Subagents | `agents/` | `retrieval-debugger`, `citation-auditor` (read-only specialists), `api-contract-reviewer` |
| Hooks | `hooks/` | PreToolUse guard (secrets, golden set, migrations, destructive commands), PostToolUse formatter, Stop checks |
| MCP server | `mcp-server/` | Scoped tools (`explain_retrieval`, `search_corpus`, `ask`, ...) that run as a service user with normal ACLs |

The files here are **copies**. The canonical versions live in `agent-capabilities/`, `agent-hooks/` and `mcp-server/` at the repository root;
`python agent-hooks/install.py` refreshes the copies and `--check` (run in CI) fails if they drift.

## Install

```text
/plugin marketplace add ./            # from the repository root (marketplace file: .claude-plugin/marketplace.json)
/plugin install citesure-agent-pack@citesure
```

Set these in the environment that starts the agent (never commit them):

```bash
export CITESURE_URL=http://localhost:8000
export CITESURE_MCP_EMAIL=agent@acme.example      # a plain workspace member (least privilege)
export CITESURE_MCP_PASSWORD=...                   # see docs/permissions.md
```

## Other tools (Codex, Cursor, Copilot, OpenCode...)

The concepts are portable: `AGENTS.md` carries the rules; the SKILL.md files are plain Markdown procedures you can load as rules/prompts;
the hook scripts read the same JSON on stdin and use exit code 2 to block; the MCP server speaks standard MCP over stdio.
See `docs/agent-extension-pack.md` for the mapping.
