# Chapter 15: Keep the secrets in, let the science in

*A private RAG system that still reads published research: a local model, an egress guard, and a network with no way out.*

**You will learn:** how to promise "our documents never leave" and prove it, how to let an assistant search papers and the web without leaking what you asked, and how to test a leak by planting a canary.
**You will build:** a second lane for published sources, a gatekeeper for everything that leaves, a local model for company text, and a Docker network that physically cannot reach the internet.
**Time:** about 4 hours. **Code and files:** `backend/app/egress/`, `backend/app/research/`, `backend/app/llm/local_provider.py`, `backend/app/services/pipeline.py`, `docker-compose.private.yml`, `deploy/egress/`, `docs/public-research.md`, `docs/private-deployment.md`.

---

## The problem

Until now CiteSure sent the retrieved passages of your documents to a hosted model to write the answer. For a handbook of fictional policies that is fine. For a real company it is not: legal may say "contracts must not leave our network", and a customer may demand it.

But "never send anything out" makes the assistant blind to everything published. A question like *"what does the research say about retrieval-augmented generation reducing hallucination?"* has nothing to do with your documents, and the answer lives in papers.

So we want two things at once:

1. **Company text stays inside.**
2. **Published text comes in.**

The trick is to stop thinking of "the assistant" as one thing. There are two **lanes**.

| Lane | Reads | Written by | Allowed to touch the internet? |
|---|---|---|---|
| Internal | your documents | a model that runs on your own machine | no |
| Public | papers, web pages | the local model, or Claude when no company text is involved | yes, through one narrow door |

## Idea 1: a model you run yourself

Chapter 6 put the model behind an interface (`LLMProvider`). That pays off now. We add a `LocalProvider` that talks to any server that speaks the common chat protocol: Ollama, vLLM, llama.cpp. Nothing else in the pipeline changes. It is slower and less clever than Claude; the honest answer is to measure it on your own questions, not to assume.

## Idea 2: refuse to start in a wrong configuration

A promise that depends on everyone remembering a setting is not a promise. With `PRIVATE_MODE=true` the server **refuses to boot** if the internal model is a hosted one, if embeddings go to a hosted API, or if the "local" model's address is a public one. Fail at boot, loudly, instead of leaking quietly for a month.

## Idea 3: one function decides who reads what

```python
def choose_llm(providers, *, internal_text, question_cleared):
    if internal_text:
        return providers.llm            # company text: the local model, always
    if providers.public_llm and question_cleared:
        return providers.public_llm     # public text only: Claude may read it
    return providers.llm
```

Behind it sits a second check, `ensure_lane_safe`, that raises an error if company text is ever about to reach a hosted model in private mode. It should never fire. It exists so that a future change that breaks the rule fails in a test instead of in production.

## Idea 4: the gatekeeper (what may leave?)

Searching a public source means sending *something* out. We keep that something tiny:

- **Keywords, not sentences.** "weeks paid parental leave caregivers", at most eight single words. No sentence of your question, and no sentence of a document, survives.
- **A guard that checks twice**, on the question and on the keywords. It blocks personal data, passwords and keys, internal addresses, "confidential" markers, a list of words you name (project code names, customers), secret **canary** strings, and, the clever one, **any run of six words that appears in one of your documents**. If someone pastes a paragraph of a policy into a public question, Postgres finds that paragraph before anything leaves.
- **A blocked message never contains the blocked text.** It says "it mentions something on the company's never-share list", not which thing, and the logs carry reason codes only. A leak detector that prints the secret is just another leak.
- **The user can see and edit the keywords first.** A "Preview what will be sent" button shows exactly what would go out. After the answer, a line says what was sent to whom.

## Idea 5: enforce it with the network, not just the code

The guard is code, and code has bugs. So the deployment adds a layer that does not trust the code at all.

```text
internal network (no route out):  api, worker, database, local model
                  │
                  └──▶ egress proxy ──▶ arXiv, Crossref, OpenAlex, Europe PMC ... (named hosts only)
```

In Docker Compose, a network marked `internal: true` has no gateway to the outside. The API lives only there. Its single way out is a small proxy (Squid) that allows named hosts over HTTPS and refuses private addresses (including the cloud metadata address that attackers love). Even if the API were fully compromised, it could not open a connection to a stranger's server.

Then we **prove** it from inside the running container with `deploy/verify-isolation.sh`:

```text
PASS  no direct route to the internet                raw sockets and DNS fail
PASS  allow-listed host reachable through the proxy  status=200
PASS  host outside the allow-list refused            refused by the proxy (403 Forbidden)
PASS  private address refused (169.254.169.254)      refused by the proxy (403 Forbidden)
```

That output is from the real stack I brought up while writing this chapter.

## Idea 6: test a leak with a canary

How do you test that nothing leaks? You plant something that must never appear anywhere, and then look everywhere. The test uploads a document containing `CANARY-7f3a-INTERNAL`, then asks questions in all three scopes while **recording every request sent to a public source and every prompt given to a hosted model**. The assertion is one line: the canary is in none of them, and neither is any company sentence. Add the attacks (the canary pasted into the question, a document sentence used as the query, a hostile paper telling the model to leak its prompt) and the test suite becomes the argument.

One design question deserves its own rule: when the question is blocked but the user supplies safe keywords, who answers? Not the hosted model, because the question text is part of its prompt. The local model reads the public papers together with the question. That is one more branch in `choose_llm`, with a test.

## What is still not solved (be honest)

- **Keywords reveal a topic.** Searching "parental leave caregivers" tells arXiv someone cares about parental leave. If the topic itself is secret, use the internal scope.
- **The guard is only as good as its lists.** An unlisted code name that never appears in a document title or text passes. Canaries and deny lists need care.
- **Scattered words** that never form a six-word run in one document are not caught.
- **A coding agent reading your chunks** sends them to its own vendor. Private mode protects the answers, not the tools next to it.

## And EvalOps?

EvalOps gates every change to CiteSure by comparing per-question pass or fail. It never needs the words. So in private mode the export replaces questions and answers with `[redacted]`, and I checked against a live EvalOps that the gate still passes, still compares with a baseline, and still fails when one question gets worse, while EvalOps stored nothing but the placeholders.

## Try it

```bash
cp .env.private.example .env
docker compose -f docker-compose.private.yml --profile setup run --rm ollama-pull
docker compose -f docker-compose.private.yml up -d --build
deploy/verify-isolation.sh
```

## Words from this chapter

**Lane**: a path through the system for one kind of source. **Egress**: data leaving. **Allow-list**: only named things are allowed, everything else is refused. **Canary**: a fake secret planted to detect leaks. **SSRF**: tricking a server into calling an internal address; the proxy and client refuse private ranges to stop it.

**Back to the index:** [The CiteSure series](00-series-index.md) · [Glossary](glossary.md)
