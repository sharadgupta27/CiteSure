# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib>=3.9"]
# ///
"""Generates the PNG figures used in the Substack guide (Substack does not render Mermaid or SVG).

    uv run substack/figures/make_figures.py

The results chart reads the real numbers from backend/evals/baseline.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "substack" / "images"
OUT.mkdir(parents=True, exist_ok=True)

INDIGO, INDIGO_L = "#4f46e5", "#e0e7ff"
GREEN, GREEN_L = "#059669", "#d1fae5"
AMBER, AMBER_L = "#d97706", "#fef3c7"
RED, RED_L = "#dc2626", "#fee2e2"
SLATE, SLATE_L = "#334155", "#f1f5f9"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 13})


def canvas(top: float, title: str | None = None):
    """A 16-inch-wide canvas whose drawing space is 100 wide and `top` tall, so 1 unit is the same on both axes."""
    fig, ax = plt.subplots(figsize=(16, 16 * top / 100), dpi=110)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, top)
    ax.axis("off")
    if title:
        ax.text(50, top - 4, title, ha="center", va="center", fontsize=20, fontweight="bold", color=SLATE)
    return fig, ax


def box(ax, x, y, w, h, text, fc=INDIGO_L, ec=INDIGO, fontsize=13, bold=False, tc=SLATE):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2", fc=fc, ec=ec, lw=2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize, fontweight="bold" if bold else "normal", color=tc, wrap=True)


def arrow(ax, x1, y1, x2, y2, color=SLATE, style="-|>", lw=2.2, ls="-"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=18, color=color, lw=lw, linestyle=ls))


def label(ax, x, y, text, fontsize=12, color=SLATE, ha="center", bold=False):
    ax.text(x, y, text, ha=ha, va="center", fontsize=fontsize, color=color, fontweight="bold" if bold else "normal")


def save(fig, name: str) -> None:
    fig.savefig(OUT / f"{name}.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", name)


# 1 ---------------------------------------------------------------------------------------------
def rag_pipeline() -> None:
    fig, ax = canvas(56, "How CiteSure answers a question")
    steps = [
        ("1. Who are you?\n(ACL)", AMBER_L, AMBER),
        ("2. Search\nvector + keyword", INDIGO_L, INDIGO),
        ("3. Rerank\nbest 6 passages", INDIGO_L, INDIGO),
        ("4. Draft answer\nclaims + quotes", INDIGO_L, INDIGO),
        ("5. VERIFY\neach claim", GREEN_L, GREEN),
        ("6. Answer\nor refuse", GREEN_L, GREEN),
    ]
    x = 2.0
    for text, fc, ec in steps:
        box(ax, x, 28, 13.5, 16, text, fc, ec, bold=True)
        x += 16
    for i in range(5):
        arrow(ax, 2 + 13.5 + 16 * i + 0.8, 36, 2 + 16 * (i + 1) - 0.4, 36)
    label(ax, 50, 14, "Only documents you are allowed to read are ever searched.   Only claims that pass the checks are ever shown.", 14, INDIGO, bold=True)
    label(ax, 50, 7, "If nothing is supported: \"I don't have information on that.\"", 13)
    save(fig, "fig-01-pipeline")


# 2 ---------------------------------------------------------------------------------------------
def acl_prefilter() -> None:
    fig, ax = canvas(68, "Why permission checks belong INSIDE the search")
    label(ax, 25, 54, "Post-filtering (leaky)", 17, RED, bold=True)
    label(ax, 75, 54, "Pre-filtering (what CiteSure does)", 17, GREEN, bold=True)
    for cx, color, light in ((25, RED, RED_L), (75, GREEN, GREEN_L)):
        box(ax, cx - 22, 30, 44, 14, "", light, color)
    label(ax, 25, 40, "Search ALL documents (HR + General)", 12.5)
    label(ax, 25, 34, "top 6: 5 HR chunks, 1 General chunk", 12.5, RED, bold=True)
    arrow(ax, 25, 29.5, 25, 22)
    box(ax, 6, 12, 38, 10, "hide the HR chunks afterwards", RED_L, RED, 12.5)
    label(ax, 25, 6, "Leaks through scores, counts and timing.\nCan also leave almost nothing to show.", 12, RED)
    label(ax, 75, 40, "Search ONLY the collections you may read", 12.5)
    label(ax, 75, 34, "top 6: 6 General chunks", 12.5, GREEN, bold=True)
    arrow(ax, 75, 29.5, 75, 22)
    box(ax, 56, 12, 38, 10, "restricted text never leaves the database", GREEN_L, GREEN, 12.5)
    label(ax, 75, 6, "WHERE collection_id IN (allowed ids)\nin the same SQL statement as the search.", 12, GREEN)
    save(fig, "fig-02-acl-prefilter")


# 3 ---------------------------------------------------------------------------------------------
def chunking() -> None:
    fig, ax = canvas(72, "Chunking: cutting a document into searchable pieces")
    label(ax, 50, 59, "One page of the handbook (sentences S1 ... S12)", 14, bold=True)
    for i in range(12):
        box(ax, 4 + i * 7.9, 46, 7.2, 8, f"S{i + 1}", SLATE_L, SLATE, 11)
    label(ax, 50, 40, "Chunks of about 4 sentences, with 1 sentence of overlap, never cutting a sentence in half", 12.5, INDIGO, bold=True)
    spans = [(0, 4), (3, 7), (6, 10), (9, 12)]
    colors = [(INDIGO_L, INDIGO), (GREEN_L, GREEN), (AMBER_L, AMBER), (RED_L, RED)]
    for k, ((a, b), (fc, ec)) in enumerate(zip(spans, colors, strict=True)):
        y = 30 - k * 7.2
        box(ax, 4 + a * 7.9, y, (b - a) * 7.9 - 0.7, 5.6, f"chunk {k + 1}", fc, ec, 11.5, bold=True)
    label(ax, 50, 3, "Every chunk is an exact slice of the page text, so a citation can highlight the right words later.", 12.5)
    save(fig, "fig-03-chunking")


# 4 ---------------------------------------------------------------------------------------------
def rrf() -> None:
    fig, ax = canvas(80, "Hybrid search: two lists, one fair merge (RRF)")
    box(ax, 8, 48, 34, 24, "", INDIGO_L, INDIGO)
    label(ax, 25, 68, "Vector search (by meaning)", 14, INDIGO, bold=True)
    box(ax, 58, 48, 34, 24, "", AMBER_L, AMBER)
    label(ax, 75, 68, "Keyword search (exact words)", 14, AMBER, bold=True)
    for i, (a, b) in enumerate((("A", "B"), ("B", "C"), ("C", "A"))):
        label(ax, 25, 61 - i * 6, f"{i + 1}.  chunk {a}", 13)
        label(ax, 75, 61 - i * 6, f"{i + 1}.  chunk {b}", 13)
    arrow(ax, 25, 47, 44, 38)
    arrow(ax, 75, 47, 56, 38)
    box(ax, 30, 20, 40, 18, "", GREEN_L, GREEN)
    label(ax, 50, 35, "After fusion", 14, GREEN, bold=True)
    label(ax, 50, 30, "1.  B   (1/62 + 1/61)", 13, bold=True)
    label(ax, 50, 26, "2.  A   (1/61 + 1/63)", 13)
    label(ax, 50, 22, "3.  C   (1/62 + 1/63)", 13)
    label(ax, 50, 12, "score(chunk) = sum over the lists of  1 / (60 + rank)", 15, INDIGO, bold=True)
    label(ax, 50, 6, "Only RANKS are used, so a cosine similarity (0 to 1) and a full-text score (any size) never need comparing.", 12)
    save(fig, "fig-04-rrf")


# 5 ---------------------------------------------------------------------------------------------
def verification() -> None:
    fig, ax = canvas(84, "Two checks between the model and you")
    box(ax, 3, 52, 20, 18, "The model drafts a claim\n+ a quote\nfrom source S2", INDIGO_L, INDIGO, 12.5, bold=True)
    arrow(ax, 23.5, 61, 31, 61)
    box(ax, 31, 52, 22, 18, "CHECK 1\nIs the quote really\nin that passage?\n(fuzzy match >= 0.9)", AMBER_L, AMBER, 12, bold=True)
    arrow(ax, 53.5, 61, 61, 61)
    box(ax, 61, 52, 22, 18, "CHECK 2\nDoes the passage\nSUPPORT the claim?\n(a second model)", AMBER_L, AMBER, 12, bold=True)
    arrow(ax, 83.5, 61, 90, 61)
    box(ax, 90, 54, 8.5, 14, "SHOWN", GREEN_L, GREEN, 12, bold=True)
    arrow(ax, 42, 51.5, 42, 38, RED)
    box(ax, 28, 28, 28, 10, "Made-up quote -> DROPPED", RED_L, RED, 12.5, bold=True)
    arrow(ax, 72, 51.5, 72, 38, RED)
    box(ax, 58, 28, 38, 10, "Real quote, wrong conclusion -> DROPPED", RED_L, RED, 12.5, bold=True)
    label(ax, 50, 17, "If every claim is dropped, the user sees a refusal, never an unchecked answer.", 14, bold=True)
    label(ax, 50, 9, "Known limit: it proves a claim is SUPPORTED, not that it is RELEVANT to the question.", 12.5, AMBER, bold=True)
    save(fig, "fig-05-verification")


# 6 ---------------------------------------------------------------------------------------------
def results_chart() -> None:
    data = json.loads((ROOT / "backend" / "evals" / "baseline.json").read_text(encoding="utf-8"))
    names = ["vector-only", "vector+rerank", "hybrid", "hybrid+rerank"]
    labels = ["vector\nonly", "vector\n+ rerank", "hybrid", "hybrid\n+ rerank\n(default)"]
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.8), dpi=110)
    panels = [("mrr", "MRR (higher is better)\nhow high the right passage ranks", INDIGO), ("answerable_refusal_rate", "Wrongly refused (lower is better)\nanswerable questions we refused", AMBER), ("restricted_refusal_accuracy", "Restricted questions refused\n(must be 100%)", GREEN)]
    for ax, (key, title, color) in zip(axes, panels, strict=True):
        values = [data[n][key] for n in names]
        bars = ax.bar(labels, values, color=color, width=0.62)
        ax.set_title(title, fontsize=13, fontweight="bold", color=SLATE)
        ax.set_ylim(0, 1.05 if key != "answerable_refusal_rate" else max(values) * 1.5 + 0.02)
        for bar, value in zip(bars, values, strict=True):
            ax.text(bar.get_x() + bar.get_width() / 2, value + (0.012 if key != "answerable_refusal_rate" else 0.003), f"{value:.2f}", ha="center", fontsize=13, fontweight="bold", color=SLATE)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(axis="x", labelsize=11)
    fig.suptitle("Real results: 40 golden questions, deterministic fake providers", fontsize=17, fontweight="bold", color=SLATE, y=1.02)
    save(fig, "fig-06-results")


# 7 ---------------------------------------------------------------------------------------------
def architecture() -> None:
    fig, ax = canvas(92, "CiteSure architecture")
    box(ax, 3, 66, 16, 12, "Browser\nReact app", SLATE_L, SLATE, bold=True)
    box(ax, 25, 66, 16, 12, "nginx\nserves UI, proxies /api", INDIGO_L, INDIGO, 11.5)
    box(ax, 47, 58, 22, 28, "FastAPI\napi -> services -> repositories\n\nACL, retrieval, generation,\nverification", INDIGO_L, INDIGO, 12, bold=True)
    box(ax, 76, 66, 21, 12, "LLM provider\n(Claude | fake)", AMBER_L, AMBER, 12)
    box(ax, 47, 30, 22, 18, "Worker\nparse, chunk, embed,\nindex, eval runs", GREEN_L, GREEN, 12, bold=True)
    box(ax, 76, 30, 21, 18, "Postgres 16\n+ pgvector + full-text\n(everything lives here)", SLATE_L, SLATE, 12, bold=True)
    box(ax, 3, 30, 16, 18, "Uploaded files\n(volume or S3)", SLATE_L, SLATE, 11.5)
    box(ax, 25, 30, 16, 18, "Embeddings\n(local ONNX)", AMBER_L, AMBER, 12)
    arrow(ax, 19.2, 72, 24.8, 72)
    arrow(ax, 41.2, 72, 46.8, 72)
    arrow(ax, 69.2, 72, 75.8, 72)
    arrow(ax, 69.2, 62, 76, 48, SLATE)
    arrow(ax, 58, 57.5, 58, 48.5, GREEN)
    arrow(ax, 69.2, 39, 75.8, 39)
    arrow(ax, 46.8, 39, 41.2, 39)
    arrow(ax, 24.8, 39, 19.2, 39)
    label(ax, 50, 18, "Jobs travel through a table in Postgres (no Redis).   Observability: Prometheus, Grafana, Loki, Tempo.", 13)
    label(ax, 50, 10, "Caddy in front for HTTPS on the single EC2 VM.   Contract: openapi.yaml.", 13)
    save(fig, "fig-07-architecture")


# 8 ---------------------------------------------------------------------------------------------
def testing_pyramid() -> None:
    fig, ax = canvas(82, "The test pyramid for a RAG system (counts from this repo)")
    box(ax, 38, 58, 24, 10, "E2E (browser)\n9", AMBER_L, AMBER, 12.5, bold=True)
    box(ax, 24, 40, 52, 15, "Integration (real Postgres + pgvector)\n72: ACL leaks, injection, worker, eval", INDIGO_L, INDIGO, 12.5, bold=True)
    box(ax, 8, 20, 84, 17, "Unit tests (fast, no Docker, fake LLM and embedder)\n94 backend  |  59 frontend  |  60 hooks  |  12 MCP  |  13 agent", GREEN_L, GREEN, 12.5, bold=True)
    label(ax, 50, 10, "Adversarial tests (prompt injection, access leaks, zip bombs) live at every level.", 13.5, RED, bold=True)
    label(ax, 50, 4, "Never call a real LLM in tests: a deterministic fake is free, fast and repeatable.", 13)
    save(fig, "fig-08-test-pyramid")


# 9 ---------------------------------------------------------------------------------------------
def agent_pack() -> None:
    fig, ax = canvas(94, "The agent extension pack")
    box(ax, 38, 70, 24, 10, "Coding agent", SLATE_L, SLATE, 14, bold=True)
    parts = [
        (3, 44, "Instructions\nAGENTS.md\nCLAUDE.md", INDIGO_L, INDIGO),
        (22, 44, "Skills (4)\nreusable\nworkflows", GREEN_L, GREEN),
        (41, 44, "Subagents (3)\nread-only\nspecialists", GREEN_L, GREEN),
        (60, 44, "MCP server\n6 scoped tools\nas a normal user", AMBER_L, AMBER),
        (79, 44, "Hooks\nguard, format,\nstop checks", RED_L, RED),
    ]
    for x, y, text, fc, ec in parts:
        box(ax, x, y, 17, 17, text, fc, ec, 12, bold=True)
        arrow(ax, x + 8.5, 69.5, x + 8.5, 61.8, ec)
    box(ax, 22, 22, 34, 12, "Plugin: bundles all of this to share", INDIGO_L, INDIGO, 12.5, bold=True)
    box(ax, 60, 22, 36, 12, "Custom agent: nightly regression watcher\n(no human, one output: an issue)", AMBER_L, AMBER, 12, bold=True)
    label(ax, 50, 12, "Advice is not enough: the hooks turn the important rules into code the agent cannot talk its way past.", 13, RED, bold=True)
    label(ax, 50, 5, "The MCP server logs in as a plain member, so the agent has exactly the access a human employee has.", 13)
    save(fig, "fig-09-agent-pack")


# 10 --------------------------------------------------------------------------------------------
def hook_flow() -> None:
    fig, ax = canvas(70, "A guardrail hook, step by step")
    box(ax, 2, 40, 17, 16, "Agent wants to:\nEdit golden.jsonl", INDIGO_L, INDIGO, 12, bold=True)
    arrow(ax, 19.5, 48, 26, 48)
    box(ax, 26, 40, 20, 16, "PreToolUse hook\n(guard.py)\nreads the event as JSON", AMBER_L, AMBER, 12, bold=True)
    arrow(ax, 46.5, 48, 53, 48)
    box(ax, 53, 40, 20, 16, "Is there a fresh\napproval with a\nreal reason?", SLATE_L, SLATE, 12, bold=True)
    arrow(ax, 73.5, 52, 80, 58, GREEN)
    box(ax, 80, 54, 17, 10, "yes: allowed", GREEN_L, GREEN, 12, bold=True)
    arrow(ax, 73.5, 44, 80, 38, RED)
    box(ax, 80, 30, 17, 14, "no: exit code 2\n+ a message that\nnames the right path", RED_L, RED, 11.5, bold=True)
    label(ax, 50, 20, "Every decision is written to an audit log (targets and decisions, never file contents).", 13)
    label(ax, 50, 12, "The guard matches the END of a path, so it still fires on unusual spellings. (Our first version did not.)", 13, RED, bold=True)
    save(fig, "fig-10-hook")


# 11 --------------------------------------------------------------------------------------------
def threat_map() -> None:
    fig, ax = canvas(88, "Where an attacker can push, and what stops them")
    rows = [
        ("Instructions hidden in a document", "delimiters + no tools +\nquote and entailment checks", RED_L, RED),
        ("Reading another team's documents", "ACL inside the SQL +\n404 + leak tests", RED_L, RED),
        ("Malicious uploads (zip bombs, fake PDFs)", "magic bytes, size and\nzip limits, sandboxed download", AMBER_L, AMBER),
        ("Stolen or guessed passwords", "bcrypt, rate limits,\nshort-lived tokens", AMBER_L, AMBER),
        ("An over-powered coding agent", "plain-member service user +\nguard hook + no write tools", INDIGO_L, INDIGO),
        ("Documents that were deleted but linger", "scrub quotes from\nstored answers", GREEN_L, GREEN),
    ]
    for i, (threat, control, fc, ec) in enumerate(rows):
        y = 66 - i * 10.2
        box(ax, 3, y, 42, 8, threat, fc, ec, 12.5, bold=True)
        arrow(ax, 45.6, y + 4, 52, y + 4, ec)
        box(ax, 52, y, 45, 8, control, "white", ec, 12)
    save(fig, "fig-11-threats")


# 12 --------------------------------------------------------------------------------------------
def deployment() -> None:
    fig, ax = canvas(72, "Deployment on one small VM")
    box(ax, 2, 36, 14, 14, "GitHub\npush to main", SLATE_L, SLATE, 12, bold=True)
    arrow(ax, 16.5, 43, 22, 43)
    box(ax, 22, 36, 18, 14, "CI: lint, types,\ntests, scans", GREEN_L, GREEN, 12, bold=True)
    arrow(ax, 40.5, 43, 46, 43)
    box(ax, 46, 36, 16, 14, "Build images\n-> GHCR", INDIGO_L, INDIGO, 12, bold=True)
    arrow(ax, 62.5, 43, 68, 43)
    box(ax, 68, 28, 29, 30, "", SLATE_L, SLATE)
    label(ax, 82.5, 54, "EC2 t3.medium", 13, SLATE, bold=True)
    box(ax, 70, 44, 11, 7, "Caddy\nHTTPS", AMBER_L, AMBER, 11)
    box(ax, 84, 44, 11, 7, "frontend\n+ API", INDIGO_L, INDIGO, 11)
    box(ax, 70, 32, 11, 7, "worker", GREEN_L, GREEN, 11)
    box(ax, 84, 32, 11, 7, "Postgres", SLATE_L, SLATE, 11)
    label(ax, 50, 18, "Deploy = pull images, run migrations, restart, poll /healthz, fail loudly if it never turns healthy.", 13)
    label(ax, 50, 9, "Embeddings and reranking run on the VM itself: no per-request cost, no data leaving.", 13)
    save(fig, "fig-12-deployment")


if __name__ == "__main__":
    for make in (rag_pipeline, acl_prefilter, chunking, rrf, verification, results_chart, architecture, testing_pyramid, agent_pack, hook_flow, threat_map, deployment):
        make()
