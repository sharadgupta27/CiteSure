# AI security audit of the codebase, with accept / fix / reject notes

**What this is.** A structured review pass over the whole code base by the coding agent (Claude Code), combining the deterministic scanner output in `scan-results/` with a manual read of the riskiest paths
(auth, upload, error handling, deployment, agent tooling). Each finding has a decision. **A human owner must review and countersign this file**; the decisions below are the agent's recommendations and what was actually changed in this session.

Method: (1) run gitleaks, Semgrep, Trivy, `pip-audit`, `npm audit`; (2) read the code for what scanners cannot see (data flowing into logs and error columns, trust boundaries, defaults); (3) fix what is cheap and clear, write a regression test for each fix, and record what is accepted and why.

## Summary

| Source | Result | Action |
|---|---|---|
| gitleaks (secrets in files) | no leaks found | none |
| Semgrep (Python, TypeScript, React, Dockerfile, GitHub Actions; 244 rules) | first run 35 findings, **all in GitHub Actions workflows**: mutable action tags, and one `workflow_run` pattern. After fixes: **1** (the `workflow_run` pattern, mitigated, A10) | 34 fixed, 1 accepted |
| Trivy (dependencies, secrets, misconfiguration) | 1 HIGH: frontend container ran as root (DS-0002) | fixed (verified `uid=101` at runtime; the Trivy filesystem re-run afterwards reports 0 vulnerabilities and 0 misconfigurations) |
| `pip-audit` | no known vulnerabilities | none |
| `npm audit` (frontend, production deps) | 2 moderate (`react-router` 6.x) | fixed by upgrading to v7 |
| `npm audit` (e2e) | 0 | none |
| Manual review | 4 additional issues (F5-F8 below) | fixed |

## Findings

### Fixed

| # | Finding | Severity | Evidence | Decision and fix |
|---|---|---|---|---|
| F1 | **GitHub Actions referenced by mutable tags** (`@v4`); Semgrep cites past compromises of popular actions | Medium (supply chain) | `semgrep.BEFORE-fix.txt` | **Fix.** Every action pinned to a full commit SHA with the tag as a comment (`security/pin_actions.py`; a CI step runs `--check`). The third-party Trivy action was replaced by running the official image directly. |
| F2 | **`workflow_run` deploy workflow checks out code**: a pull request from a *fork* with a branch named `main` could trigger a deployment-capable workflow | High (if secrets were present) | Semgrep `workflow-run-target-code-checkout` | **Mitigated (Semgrep still reports it).** The deploy job now also requires the triggering CI run's event to be `push` and its head repository to be this repository, so only code already on this repo's branches is ever checked out. The rule matches the pattern, not the condition, so the single remaining finding is **accepted** as A10 below. |
| F3 | **Frontend container ran nginx as root** | High (container escape impact) | Trivy DS-0002 | **Fix.** Switched to `nginxinc/nginx-unprivileged` (port 8080), `USER nginx`; verified `uid=101(nginx)`. |
| F4 | **`react-router` 6.x advisories** (open redirect in `<Link>`/`navigate`, constructor injection in SSR hydration) | Moderate | `npm-audit-frontend.BEFORE-fix.txt` | **Fix** by upgrading to v7 (0 vulnerabilities, all 59 tests still pass). Practical exposure was low: no user-controlled link targets, no SSR. |
| F5 | **Database driver errors could carry document text into the database and logs.** SQLAlchemy puts bound parameter values in error messages; for chunks those are document text. The ingestion error was stored in `documents.error` and shown to admins. | High (confidentiality) | seen while debugging an ingestion failure (`[parameters: ...]`) | **Fix.** `hide_parameters=True` on every engine; ingestion stores only the exception **type**; the answer pipeline logs only the type. Regression test `test_ingestion_errors_never_store_document_text`. |
| F6 | **Development JWT secret was shorter than the recommended HS256 key length and nothing warned when it was in use** | Medium | Loki log panel in Grafana (`InsecureKeyLengthWarning`) | **Fix.** Longer dev default; a startup WARNING when the built-in secret is active; production already refuses it (`assert_safe_for_prod`, tested). |
| F7 | **Worker container always reported "unhealthy"** (inherited the API's `/healthz` probe), hiding real failures behind permanent noise | Low (operational) | `docker compose ps` | **Fix.** Worker healthcheck probes its own metrics port, in dev and prod compose. |
| F8 | **Deleting a document left its quoted text in stored answers** | High (data retention) | found while writing `ai-data-policy.md` | **Fix.** Deletion scrubs citations from stored answers; test added (`test_deleting_a_document_also_erases_...`). |

### Accepted (with reasons and mitigations)

| # | Finding | Why accepted | Mitigation / when to revisit |
|---|---|---|---|
| A1 | JWT stored in `localStorage` (readable by XSS) | A cookie-based session needs CSRF handling and a refresh design; out of MVP scope | Strict CSP, React escaping, no raw HTML sinks. **Backlog #1** in the threat model. |
| A2 | Rate limits are in memory per process | One API process in the demo deployment | Use the proxy or Redis for more replicas. |
| A3 | Registration is open | A new account can read nothing until an admin adds it | Disable or invite-only for real deployments; documented in the threat model. |
| A4 | Workspace admins can read every collection | Admins own the knowledge base; simple, testable rule | Documented in `permissions.md`; the agent never gets an admin account. **Backlog #2.** |
| A5 | Multipart uploads are fully received before the app-level size check | The proxies cap bodies first (Caddy 25 MB, nginx 25 MB) | In dev compose the API port is published without a proxy; do not expose it. |
| A6 | `TRUST_PROXY_HEADERS=true` in the dev compose file while the API port is published | Needed so the rate limiter sees the client behind nginx | Production does not publish the API. Do not expose dev compose to the internet. |
| A7 | bcrypt truncates passwords at 72 bytes | Library behaviour; very long passwords are rare | Passwords are length-limited at 128 characters on input. |
| A8 | PII detection is regex-based | Presidio would need a model download | Threat model T4; redaction available (`PII_REDACT`). |
| A9 | No malware scan on uploads | Out of scope for MVP | Parsers run in a non-root worker container; magic-byte validation and size limits apply. **Backlog #4.** |

| A10 | Semgrep `workflow-run-target-code-checkout` still fires on `deploy.yml` (1 finding after fixes, down from 35) | The job's `if:` allows only successful CI runs from a `push` whose head repository equals this repository; fork pull requests can never reach the checkout. The pattern-based rule cannot see that condition. | Re-check if the trigger or the `if:` changes. Alternative if it must go to zero: move deploy into `ci.yml` as a job that `needs:` the others (no `workflow_run`). |

### Rejected suggestions

| # | Suggestion | Why rejected |
|---|---|---|
| R1 | "Filter restricted chunks after retrieval for speed" | The core design rule is that access control lives in the retrieval SQL (post-filtering leaks through scores, counts and timing, and can starve results). |
| R2 | "Let the evaluation personas be normal users that can log in" | They have random, unusable passwords on purpose; they exist only to exercise the access rules. |
| R3 | "Reject `.invalid` addresses when creating personas instead of hiding them" | Hiding system users from admin lists is more robust than trying to keep them out of every code path (found via a real 500). |
| R4 | "Raise bcrypt cost to 14" | Login latency would more than quadruple for a small gain; rate limits already bound guessing. Revisit with hardware changes. |
| R5 | "Silence the Semgrep `workflow_run` rule" | It found a real problem (F2); we fixed the code instead of ignoring the rule. |
| R6 | "Add a global exception handler that returns the exception message for easier debugging" | Messages can contain document text (F5). The handler returns a generic message and logs the type only. |

## Residual risk and next steps

See `threat-model.md` (T6, T7, T8 and the hardening backlog). The three most valuable next steps: cookie-based sessions with refresh rotation; separating "manage" from "read" for admins; an answer-relevance check (not a security control, but it closes the "verified but irrelevant" gap).

## Reviewer countersignature

| Reviewer | Date | Decision | Notes |
|---|---|---|---|
| _(project owner)_ | | accept / amend | |
