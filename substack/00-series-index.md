# Build a RAG system you can trust: the CiteSure series

*A step-by-step guide, in plain language, to building an AI document assistant that shows its sources, checks them, and keeps secrets secret.*

---

## What you will build

Imagine you work at a company with hundreds of policy pages. You ask: **"How many weeks of paid parental leave do I get?"**

A normal chatbot answers confidently. Maybe it is right. Maybe it made it up. You cannot tell. And if the company also keeps confidential HR files, a careless chatbot may read those too, and tell the wrong person.

**CiteSure** is the opposite. It:

1. gives every sentence of its answer a **citation** (document, section, and the exact words it relied on),
2. **checks** every citation before you see it, and drops anything it cannot prove,
3. only ever searches documents **you are allowed to read**, and
4. comes with a **scoreboard** so you can prove it works (and notice when it stops working).

![An answer with numbered citations](images/02-answer-with-citations.png)

You will build the whole thing: the search engine, the checking logic, the web app, the tests, the Docker setup, the monitoring, and a set of **tools that let an AI coding agent work on the project safely**.

Everything in this series is real. The code runs. The numbers are measured. When something went wrong while I built it, I tell you what, why, and how it was fixed, because that is where the learning is.

## Who this is for

- You can read a little Python or JavaScript. You do **not** need to know what "RAG" means yet; chapter 1 explains it.
- You want a portfolio project that shows more than "I called an AI API". (Hiring managers for AI engineering roles want to see evaluation, security, tests and deployment. This project has all four.)
- You use, or want to use, an AI coding assistant (Claude Code, Codex, Cursor...) and want to know how to keep it on a leash.

## How to follow along

All the code is in one repository. Every chapter says which files it is about. You can:

- **read only** (each chapter stands on its own), or
- **run it as you go** (`docker compose up` gives you the finished app in two minutes), or
- **rebuild it from scratch** by following the steps.

You need Docker, Python 3.12 with [uv](https://docs.astral.sh/uv/), and Node 22. You do **not** need an API key: the project ships with deterministic "fake" AI parts so everything runs free and offline. (Chapter 7 explains why that is a feature, and what it can and cannot tell you.)

## The chapters

| # | Title | The one idea | Figure |
|---|---|---|---|
| 1 | [Start RAG with the test set, not the vector database](01-start-with-the-eval-set.md) | Write the exam before you build the student | pipeline |
| 2 | [Contract first: write the menu before you cook](02-contract-first.md) | One file describes the API; everything else follows it | |
| 3 | [Permission-aware RAG](03-permission-aware-rag.md) | Check permissions *inside* the search, never after | ACL |
| 4 | [Chunking is a product decision](04-chunking-is-a-product-decision.md) | How you cut a document decides what you can find | chunking |
| 5 | [Hybrid search and reranking, with real failures](05-hybrid-search-and-reranking.md) | Two ways of searching beat one, and a second opinion beats both | RRF |
| 6 | [Make the AI cite its sources, and catch it when it lies](06-making-llms-cite-and-catching-lies.md) | Never show a claim you have not checked | verification |
| 7 | [Measuring RAG](07-measuring-rag.md) | If you cannot measure it, you cannot improve it | results |
| 8 | [A UI people trust](08-a-ui-people-trust.md) | Citations change how an AI answer *feels* | screenshots |
| 9 | [Testing a RAG system](09-testing-a-rag-system.md) | Unit, integration, adversarial, end to end | pyramid |
| 10 | [Ship it](10-ship-it.md) | Docker, CI/CD and an honest note on deployment | deployment |
| 11 | [Watching a RAG system in production](11-observing-rag.md) | Graph the right things, alert on the right changes | dashboard |
| 12 | [Giving coding agents safe access with MCP, skills and hooks](12-agent-extension-pack.md) | Advice is not enough: enforce rules with code | agent pack, hook |
| 13 | [The RAG threat model](13-rag-threat-model.md) | Prompt injection, leaks, uploads, PII, and what we found | threats |
| 14 | [Lessons, results and what to do next](14-lessons-and-launch.md) | What worked, what did not, how to describe it on a résumé | |

A [glossary](glossary.md) explains every technical word in one or two sentences. Skim it first if you like.

## The three promises, and how we keep them

These come back in every chapter, so here they are once:

| Promise | How it is enforced | Where it is tested |
|---|---|---|
| **No unverified claim reaches a user.** | Every answer passes a two-step check. Anything that fails is removed. | chapters 6 and 9 |
| **You only get answers from documents you may read.** | The permission filter is part of the database query itself. | chapters 3 and 9 |
| **Text inside a document is data, not orders.** | Documents are fenced off in the prompt, the model has no tools, and its claims are checked anyway. | chapters 6 and 13 |

Ready? [Chapter 1: start with the test set, not the vector database →](01-start-with-the-eval-set.md)
