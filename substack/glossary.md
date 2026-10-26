# Glossary

Every technical word used in the series, in one or two plain sentences. Alphabetical.

**ACL (access control list).** The rules that say who may read what. In CiteSure: members read workspace-visible collections plus the collections of their groups; admins read all collections in their workspace.

**Agent (coding agent).** An AI assistant that can read files, run commands and call tools on your behalf, not only chat. Claude Code, Codex and Cursor are examples.

**AGENTS.md / CLAUDE.md.** Plain Markdown files at the root of a project that tell a coding agent the rules, commands and boundaries.

**Alembic.** The tool that records every change to the database structure as a numbered "migration" file.

**Alert.** A rule that sends a message when a metric looks wrong (for example, too many refused questions for 15 minutes).

**API.** The set of web addresses a program can call. Here, the backend's API is what the web page and the MCP server talk to.

**Append-only.** A file you may add lines to but never change or delete lines from. The golden question set is append-only.

**Audit log.** A record of what happened (who, what, allowed or blocked), kept so you can check afterwards. Ours stores decisions, never file contents.

**bcrypt.** A deliberately slow way to scramble passwords so stolen databases are hard to crack.

**Caddy.** A web server that gets free HTTPS certificates automatically. It is the front door in the production setup.

**Chunk.** A passage of a document (here, around 400 tokens) that the search engine stores and retrieves as one piece.

**Citation.** A pointer from a claim in the answer to the document, section and exact words that support it.

**CI / CD.** Continuous Integration: a robot runs all the checks on every change. Continuous Delivery: a robot ships the change when the checks pass.

**Claim.** One short statement in an answer, with its own citations. The unit that gets verified.

**Collection.** A folder of documents with one access rule (for example `General`, `People-Ops-Confidential`).

**Container / image / Docker.** An image is a packaged app with everything it needs. A container is a running copy. Docker is the tool that builds and runs them.

**Contract-first.** Writing the description of the API (`openapi.yaml`) before the code, then generating or checking everything against it.

**Cross-encoder.** A model that reads the question and a passage *together* and scores how well they match. Slower but more accurate than comparing two separate vectors; used for reranking.

**CSP (Content-Security-Policy).** A browser rule that limits which scripts and resources a page may load. A defence against XSS.

**Embedding.** A list of numbers (here, 384) that represents the meaning of a text, so similar texts have similar numbers.

**Entailment.** "Does this passage really support this claim?" The second verification step asks a model to judge: supported, partial or unsupported.

**Eval / evaluation / golden set.** A fixed list of questions with known correct answers and sources, used to measure the system. Ours has 40.

**Faithfulness.** The share of drafted claims that survived verification.

**Fail open / fail closed.** When a safety check hits something unexpected: failing open lets the action through (dangerous); failing closed blocks it (safe).

**Fake provider.** A deterministic stand-in for the AI model or embedder used in tests, so tests are free, fast and repeatable. It cannot tell you how good a real model is.

**FTS (full-text search).** Keyword search built into Postgres. Good at exact words like policy codes.

**Grafana / Prometheus / Loki / Tempo.** Dashboards / numbers over time / logs / request traces: the monitoring toolbox.

**Hallucination.** When a model states something that its sources do not support.

**Hash chain.** Each audit-log entry includes a fingerprint (hash) of the previous entry, so changing or removing an entry in the middle breaks every fingerprint after it. Removing only the newest entries is not detected unless you keep a copy of the latest hash elsewhere.

**Hook.** A small script a coding tool runs automatically at a set moment (before an action, after an edit, when the agent says "done"). It can block the action.

**HNSW.** A kind of index that finds the nearest vectors quickly without comparing against all of them.

**Hybrid search.** Using both vector search (meaning) and keyword search (exact words), then combining the results.

**Injection (prompt injection).** Text inside a document that tries to give the model orders ("ignore your rules..."). Defended by treating document text as data.

**JWT.** A signed token the browser sends to prove who you are.

**MCP (Model Context Protocol).** A standard way to give an AI agent a menu of tools. Our MCP server offers six read-mostly tools.

**Migration.** A numbered script that changes the database structure.

**MRR (mean reciprocal rank).** For each question, 1 divided by the position of the first correct chunk (1st = 1.0, 2nd = 0.5...), averaged. Higher means the right chunk is nearer the top.

**Observability.** Being able to tell what a running system is doing from the outside: metrics, logs and traces.

**OCR (optical character recognition).** Reading the text out of a picture of a page, so a scanned PDF becomes searchable. Optional in CiteSure, done locally with Tesseract.

**OIDC (OpenID Connect).** A standard way to sign in with an account from another provider (Keycloak, Microsoft Entra, Google) instead of a password stored by the app.

**OpenAPI.** A standard file format for describing an API.

**pgvector.** A Postgres extension that stores embeddings and searches them by similarity.

**PII.** Personally identifiable information: emails, phone numbers, ID numbers.

**Plugin.** A bundle of skills, subagents, hooks and tool settings that can be installed into another project.

**Pre-filter.** Applying a rule (here, permissions) inside the search itself, rather than removing results afterwards.

**Quarantine.** A holding place for a file the system will not import yet, for example one dropped in a watched folder that matches no collection. It is never imported with broader access.

**RAG (retrieval-augmented generation).** First *find* relevant passages from your documents, then ask a model to answer *using only those passages*.

**Recall@k.** Of the passages that should have been found, the share that appeared in the top k results.

**Refusal.** The system's answer "I don't have information on that" when nothing could be verified.

**Rerank.** A second pass that reorders the top candidates using a more accurate (slower) model.

**RRF (reciprocal rank fusion).** A simple way to merge two ranked lists: each item scores 1/(60 + its rank) in each list, and the scores are added.

**Semgrep / Trivy / gitleaks.** Security scanners: risky code patterns / known-vulnerable packages and container mistakes / secrets in files.

**Skill.** A Markdown procedure the agent loads when it is relevant, so repeated jobs are done the same careful way.

**SSE (Server-Sent Events).** A way for the server to push messages to the browser one by one over a single connection. Used for the "Searching... Writing... Checking..." progress.

**Study set.** A personal reading list of documents (and saved papers) with reading progress tracked across them.

**Subagent.** A helper agent with a clean context and a limited tool list, which the main agent can delegate a job to.

**Testcontainers.** A test library that starts a real database in a container for the test session and throws it away afterwards.

**Threat model.** A table of what you protect, who could attack it, what stops them, how you know, and what risk remains.

**Token.** A piece of text (roughly three-quarters of a word) that models read and bill by. Also: a login token (see JWT).

**Vault.** Encryption of uploaded files at rest with a key you provide, so a copy of the disk is unreadable without it.

**Vector search.** Finding the passages whose embeddings are closest to the question's embedding: search by meaning.

**Verification.** The two checks every claim must pass before the user sees it: the quote exists in the cited chunk, and the chunk supports the claim.

**Worker.** A background process that does slow jobs (parsing, chunking, embedding documents) so the web request can return immediately.

**XSS (cross-site scripting).** An attack where a malicious script runs inside your page in the victim's browser.
