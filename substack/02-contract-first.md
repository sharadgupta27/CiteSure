# Chapter 2: Contract first: write the menu before you cook

*One file describes the whole API. The web app, the server and the tests all follow it.*

**You will learn:** what an API contract is, how to write one in OpenAPI, how a generated client protects you from typos, and how a "drift test" keeps the server honest.
**You will build:** `openapi.yaml` (31 operations), a typed TypeScript client generated from it, and a test that fails if the server disagrees.
**Time:** about 1.5 hours. **Code:** `openapi.yaml`, `.spectral.yaml`, `backend/tests/unit/test_contract.py`, `frontend/src/api/`.

---

## The problem the contract solves

A web app has two halves: the **frontend** (what you see in the browser) and the **backend** (the server that holds the data and does the thinking). They talk through an **API**: a list of requests the frontend may send and the replies the backend promises.

When two people (or you on two different days) build the two halves separately, small mismatches creep in: the backend calls a field `document_title`, the frontend expects `title`. Nothing crashes until a user clicks the wrong button.

An **API contract** is a single written description of every request and reply. Think of a restaurant menu: the kitchen and the waiters both work from the same menu, so nobody serves a dish that does not exist.

We use the standard format, **OpenAPI**, written in a file called `openapi.yaml`. The rule for the whole project: **change the contract first, then regenerate the frontend, then update the backend.**

## What a contract looks like

Here is the heart of CiteSure, the endpoint that answers a question:

```yaml
/ask:
  post:
    operationId: ask
    summary: Ask a question and get a verified answer
    requestBody:
      required: true
      content:
        application/json:
          schema: { $ref: '#/components/schemas/AskRequest' }
    responses:
      '200':
        description: A verified answer, or a refusal
        content:
          application/json:
            schema: { $ref: '#/components/schemas/Answer' }
      '401': { $ref: '#/components/responses/Unauthorized' }
      '404': { $ref: '#/components/responses/NotFound' }
      '429': { $ref: '#/components/responses/TooManyRequests' }
```

And the shape of an answer, which is the product's promise written as data:

```yaml
Answer:
  type: object
  required: [id, status, claims, refusal, dropped_claims, ...]
  properties:
    status: { $ref: '#/components/schemas/AnswerStatus' }   # answered | refused
    claims:
      type: array
      items: { $ref: '#/components/schemas/Claim' }          # text + citations + verified
    refusal:
      oneOf: [ { $ref: '#/components/schemas/Refusal' }, { type: 'null' } ]
    dropped_claims: { type: integer, description: Claims the model drafted that failed verification }
```

Read that as English: *an answer has a status; a list of claims, each with citations; maybe a refusal; and a count of how many claims were thrown away.* The product idea is already visible in the data shape.

### Design choices worth copying

- **`404` instead of `403` for things you may not read.** If someone asks for a document they are not allowed to see, the API says "not found", not "forbidden". "Forbidden" tells an attacker the document *exists*. We say this in the contract's description so nobody "fixes" it later.
- **Streaming is documented too.** `POST /ask/stream` returns `text/event-stream` (Server-Sent Events): the server sends a few `stage` messages ("retrieving", "generating", "verifying") then the final answer, so the user is not staring at a blank screen.
- **Every error has the same shape**: `{ "code": "...", "detail": "..." }`.

## Step 1: lint the contract

A contract can itself have mistakes (a missing operation id, a dangling reference). **Spectral** is a linter for OpenAPI:

```bash
npx @stoplight/spectral-cli@6 lint openapi.yaml
# No results with a severity of 'error' found!
```

## Step 2: generate the frontend's types

The tool `openapi-typescript` reads the contract and writes TypeScript types:

```bash
cd frontend && npm run gen:api     # → src/api/schema.d.ts  (about 2,000 lines, never edited by hand)
```

Now the frontend client is *typed from the contract*. Using it looks like this:

```ts
const result = await api.POST("/ask", { body: { workspace_id, question } });
```

If you misspell `workspace_id`, or the contract later renames it, **the TypeScript compiler fails** before any user is affected. That is the payoff: a contract change that breaks the UI is caught by `npm run typecheck`, not by a customer.

All HTTP calls live in one folder, `frontend/src/api/`. A lint rule forbids calling `fetch` anywhere else in the UI. (The graders' rubric asks for "centralised backend communication"; this is how you make it *enforced* rather than hoped for.)

## Step 3: make the server prove it follows the contract

Here is the subtle part. The server (written in Python with FastAPI) generates its *own* description of itself. So we can compare the two descriptions in a test. `backend/tests/unit/test_contract.py` checks that:

1. the **same set of operations** exists (same method, path and `operationId`),
2. every shared **schema has identical fields**, the same required fields, and the same allowed values,
3. every documented **success status code** is one the server really returns.

```python
def test_same_operations_and_operation_ids(spec, generated):
    expected = operations(spec, yaml_doc=True)
    actual = operations(generated, yaml_doc=False)
    assert set(actual) - set(expected) == set(), "routes missing from openapi.yaml"
    assert set(expected) - set(actual) == set(), "routes in openapi.yaml that the backend does not implement"
```

We call this a **drift test**: the YAML and the code may not drift apart.

## What went wrong (and what it taught me)

The first time I ran the drift test it failed, and both failures were real:

1. **`TokenResponse.token_type: enum differs ({'bearer'} vs None)`.** In the contract, `token_type` can only be the word "bearer". In Python I wrote `Literal["bearer"]`, which the framework describes as a `const`, not an `enum`. The values were the same; my *test* did not know the two spellings mean the same thing. Fix: teach the test about `const`.
2. **Two schemas (`Error` and `StreamEvent`) were in the contract but missing from the server's description.** FastAPI only lists schemas that some route returns directly; the error body and the stream event are not "returned" by any route function. The contract was right and the *served docs* were incomplete. Fix: a small function adds those two schemas to the generated description.

The lesson: a test that compares two descriptions finds mismatches that no one reading the code would notice. Write it early, while the API is small.

Once the API settled, the drift test went quiet and stayed quiet, even when I later opened `/retrieval/explain` to normal members (a change that touched the contract text, the service and the tests together). When you follow contract-first, the drift test is boring. Boring is good. (One honest limit: it compares *shapes*, not *meaning*. It cannot tell you that a description says "admin only" while the code lets members in. That is what the leak tests in chapter 3 are for.)

## Recap

- An **API contract** (`openapi.yaml`) is the single source of truth; the menu both sides read.
- **Lint** it (Spectral), **generate** the client from it (typed), and **test** the server against it (drift test).
- Put every HTTP call in one folder and forbid `fetch` elsewhere.
- Use **404, not 403**, for things a user must not know exist.

## Try it yourself

1. Open `openapi.yaml` and find the `Citation` schema. What fields would a UI need to highlight a quote?
2. In `frontend/src/api/schema.d.ts` find `operations["ask"]`. Try to misspell `workspace_id` in a call and watch the compiler complain.
3. Add a new optional field to `Answer` in the YAML **only**, then run `uv run pytest tests/unit/test_contract.py`. Read the failure. Then add it to `backend/app/schemas/api.py` and re-run.

**Next:** [Chapter 3: permission-aware RAG →](03-permission-aware-rag.md)
