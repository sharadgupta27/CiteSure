"""CiteSure MCP server.

Gives a coding agent a SMALL, SCOPED set of tools to diagnose answers and retrieval, instead of database access:

  tools      list_collections, search_corpus, get_chunk, explain_retrieval, ask, run_eval
  resource   citesure://documents/{document_id}
  prompt     diagnose-bad-answer

Security model (docs/permissions.md): the server logs in as a service user. Every call goes through the normal HTTP API,
so the ACL that protects human users protects the agent too. The default service user is a plain workspace member:
it cannot read restricted collections, and `run_eval` (admin only) returns a permission error. There are no write or
delete tools. Tool output is truncated, and no tokens or passwords are ever returned.

Run it (stdio):  uv run --project mcp-server python mcp-server/server.py
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from citesure_client import CiteSureClient, CiteSureError
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

# httpx logs full request URLs at INFO, and the explain call carries the question text. Keep questions out of logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = MCPServer(
    "citesure",
    instructions=(
        "Tools to diagnose CiteSure answers and retrieval. Everything is read-only except `ask` (stores a history entry) and "
        "`run_eval` (stores one evaluation run). You only see what the configured service user may read."
    ),
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITES_A_RECORD = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
_client: CiteSureClient | None = None

MAX_TEXT = 1200  # characters of chunk text returned per item: enough to diagnose, too little to dump a corpus
EVAL_POLL_SECONDS = 90


def client() -> CiteSureClient:
    global _client
    if _client is None:
        _client = CiteSureClient.from_env()
    return _client


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    return text if len(text) <= limit else text[:limit] + f"… [{len(text) - limit} more characters]"


def _fail(error: CiteSureError) -> str:
    return f"ERROR: {error}"


@mcp.tool(annotations=READ_ONLY)
async def list_collections() -> str:
    """List the collections (and their access mode) that the service user may read in its workspace."""
    try:
        workspace_id = await client().default_workspace_id()
        collections = await client().request("GET", f"/workspaces/{workspace_id}/collections")
    except CiteSureError as error:
        return _fail(error)
    return json.dumps(
        {
            "workspace_id": workspace_id,
            "collections": [{"id": c["id"], "name": c["name"], "visibility": c["visibility"]} for c in collections],
        },
        indent=2,
    )


@mcp.tool(annotations=READ_ONLY)
async def explain_retrieval(query: str, retrieval_mode: str = "hybrid", rerank: bool = True) -> str:
    """Show every retrieval stage for a query: vector hits, keyword hits, fused ranking and the reranked top chunks,
    each with rank, score and a snippet. Use it to see WHERE the right chunk was lost (not retrieved, ranked low,
    or dropped by the reranker). Shows only chunks the service user may read.

    retrieval_mode: "hybrid" (vector + keyword) or "vector". rerank: whether to apply the reranker."""
    if retrieval_mode not in {"hybrid", "vector"}:
        return "ERROR: retrieval_mode must be 'hybrid' or 'vector'"
    try:
        workspace_id = await client().default_workspace_id()
        trace = await client().request(
            "GET",
            "/retrieval/explain",
            params={"workspace_id": workspace_id, "query": query, "retrieval_mode": retrieval_mode, "rerank": rerank},
        )
    except CiteSureError as error:
        return _fail(error)

    def stage(name: str) -> dict[str, Any]:
        return {
            name: [
                {"rank": c["rank"], "score": c["score"], "chunk_id": c["chunk_id"], "document": c["document_title"], "snippet": c["snippet"]}
                for c in trace[name][:10]
            ]
        }

    return json.dumps(
        {"query": trace["query"], "config": trace["config"], "allowed_collections": trace["allowed_collections"]}
        | stage("vector")
        | stage("fts")
        | stage("fused")
        | stage("reranked"),
        indent=2,
    )


@mcp.tool(annotations=READ_ONLY)
async def search_corpus(query: str, limit: int = 5) -> str:
    """Find the most relevant chunks for a query (hybrid search plus rerank) and return their text. Read-only."""
    limit = max(1, min(limit, 10))
    try:
        workspace_id = await client().default_workspace_id()
        trace = await client().request(
            "GET", "/retrieval/explain", params={"workspace_id": workspace_id, "query": query, "retrieval_mode": "hybrid", "rerank": True}
        )
        hits = trace["reranked"][:limit]
        results = []
        for hit in hits:
            chunk = await client().request("GET", f"/chunks/{hit['chunk_id']}")
            results.append(
                {
                    "chunk_id": chunk["id"],
                    "document": chunk["document_title"],
                    "section": " > ".join(chunk["heading_path"]),
                    "page": chunk["page_start"],
                    "score": hit["score"],
                    "text": _clip(chunk["text"]),
                }
            )
    except CiteSureError as error:
        return _fail(error)
    return json.dumps(results, indent=2)


@mcp.tool(annotations=READ_ONLY)
async def get_chunk(chunk_id: str) -> str:
    """Fetch one chunk (text, section, page and character offsets). Returns an error if the service user may not read it."""
    try:
        chunk = await client().request("GET", f"/chunks/{chunk_id}")
    except CiteSureError as error:
        return _fail(error)
    chunk["text"] = _clip(chunk["text"], 4000)
    return json.dumps(chunk, indent=2)


@mcp.tool(annotations=WRITES_A_RECORD)
async def ask(question: str) -> str:
    """Ask CiteSure a question exactly as a user would. Returns the verified claims with their citations, or the refusal,
    plus how many drafted claims verification dropped and per-stage latency. This stores the question in the history."""
    try:
        workspace_id = await client().default_workspace_id()
        answer = await client().request("POST", "/ask", json={"workspace_id": workspace_id, "question": question})
    except CiteSureError as error:
        return _fail(error)
    summary: dict[str, Any] = {
        "status": answer["status"],
        "dropped_claims": answer["dropped_claims"],
        "latency_ms_by_stage": answer["latency_ms_by_stage"],
    }
    if answer["status"] == "answered":
        summary["claims"] = [
            {
                "text": c["text"],
                "verification": c["verification"],
                "citations": [
                    {"chunk_id": x["chunk_id"], "document": x["document_title"], "quote": x["quote"]} for x in c["citations"]
                ],
            }
            for c in answer["claims"]
        ]
    else:
        summary["refusal"] = answer["refusal"]
    return json.dumps(summary, indent=2)


@mcp.tool(annotations=WRITES_A_RECORD)
async def run_eval(name: str, retrieval_mode: str = "hybrid", rerank: bool = True, top_k: int = 6) -> str:
    """Run the golden-set evaluation with the given configuration and return its metrics. Needs a workspace ADMIN service
    user; a plain member gets a permission error. It may take up to a minute. It only reads the golden set and writes
    one evaluation run record; it cannot change the golden set."""
    if retrieval_mode not in {"hybrid", "vector"}:
        return "ERROR: retrieval_mode must be 'hybrid' or 'vector'"
    try:
        workspace_id = await client().default_workspace_id()
        run = await client().request(
            "POST",
            f"/workspaces/{workspace_id}/eval-runs",
            json={"name": name[:100], "config": {"retrieval_mode": retrieval_mode, "rerank": rerank, "candidate_k": 30, "top_k": max(1, min(top_k, 20))}},
        )
        for _ in range(EVAL_POLL_SECONDS):
            detail = await client().request("GET", f"/eval-runs/{run['id']}")
            if detail["status"] in {"done", "failed"}:
                weak = [i["question"] for i in detail["items"] if i["answerable"] and i["answer_status"] == "refused"][:5]
                return json.dumps(
                    {"run_id": run["id"], "status": detail["status"], "error": detail["error"], "metrics": detail["metrics"], "answerable_but_refused": weak},
                    indent=2,
                )
            await asyncio.sleep(1)
    except CiteSureError as error:
        return _fail(error)
    return json.dumps({"run_id": run["id"], "status": "still running; call again later or check the Quality page"})


@mcp.resource("citesure://documents/{document_id}")
async def document_resource(document_id: str) -> str:
    """A document's metadata and chunks (ACL-checked), for the agent to read as context."""
    document = await client().request("GET", f"/documents/{document_id}")
    chunks = await client().request("GET", f"/documents/{document_id}/chunks")
    return json.dumps(
        {
            "title": document["title"],
            "status": document["status"],
            "chunks": [{"id": c["id"], "section": " > ".join(c["heading_path"]), "text": _clip(c["text"])} for c in chunks[:50]],
        },
        indent=2,
    )


@mcp.prompt(name="diagnose-bad-answer")
def diagnose_bad_answer(question: str, expected: str = "", actual: str = "") -> str:
    """A step-by-step procedure for finding why CiteSure answered a question badly."""
    return f"""A user reports a bad answer from CiteSure.

Question: {question}
Expected: {expected or "(not given)"}
Actual:   {actual or "(not given)"}

Diagnose it in this order, stopping at the first stage that is at fault:
1. Call `ask` with the question. Note status, dropped_claims and the citations.
2. Call `explain_retrieval` with the question. Is a chunk containing the expected fact in `vector`, `fts`, `fused`, `reranked`?
   - Not in any list: parsing or chunking problem (use `get_chunk` / the document resource to read the stored text).
   - In `fused` but missing from `reranked`: reranking problem.
   - In `reranked` but the answer is wrong: generation or verification problem (see dropped_claims).
3. Say which stage failed, quote the evidence (chunk ids, ranks), and propose ONE fix with its risk.
4. Do not edit evaluation data to make the answer pass. Propose a new golden question with the add-golden-question skill instead."""


if __name__ == "__main__":
    mcp.run()
