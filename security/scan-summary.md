# Security scan summary

Raw outputs are in [scan-results/](scan-results/). Reproduce everything with `bash security/run-scans.sh` (needs Docker; downloads scanner images). Analysis and decisions: [ai-pr-audit.md](ai-pr-audit.md). Threats and controls: [threat-model.md](threat-model.md).

| Scanner | Looks at | Result now | Before fixes | Evidence |
|---|---|---|---|---|
| gitleaks | secrets in the working tree | **no leaks found** | same | `scan-results/gitleaks.txt` |
| Semgrep (244 rules: Python, TypeScript/React, Dockerfile, GitHub Actions) | code patterns | **1 finding**: `workflow-run-target-code-checkout` in `deploy.yml`, mitigated by an `if:` condition, accepted as A10 | **35** (mutable action tags + the same rule) | `semgrep.txt`, `semgrep.BEFORE-fix.txt` |
| Trivy filesystem (vulnerabilities, secrets, misconfiguration) | lockfiles, Dockerfiles | **0 vulnerabilities, 0 misconfigurations** (backend, frontend, MCP server lockfiles; both Dockerfiles) | 1 HIGH: frontend image ran as root (DS-0002) | `trivy-fs.txt` (the before-fix output was not saved; the finding is described in the audit) |
| `pip-audit` | Python dependencies | **no known vulnerabilities** | same | `pip-audit.txt` |
| `npm audit` (frontend, production) | JS dependencies | **0 vulnerabilities** | 2 moderate (`react-router` 6.x) | `npm-audit-frontend.txt`, `npm-audit-frontend.BEFORE-fix.txt` |
| `npm audit` (e2e) | test tooling | 0 | 0 | `npm-audit-e2e.txt` |

## What was not done

- The **built backend image** was not scanned in this session (CI does it: job `images`). Only the filesystem scan ran.
- Scanner runs in **GitHub Actions** were not executed on GitHub (no remote). Every command was run locally.
- No **dynamic** testing (DAST), no penetration test, no dependency-confusion review beyond lockfiles.
- Dependabot is not enabled (needs the repository on GitHub).

## Manual findings (not found by scanners)

F5 (document text in database errors), F6 (short dev JWT secret), F7 (worker healthcheck), F8 (deleted document text left in stored answers): see `ai-pr-audit.md`. Each has a regression test or a verification command listed there.

**Scanner output is not a guarantee.** It says "none of these known patterns were found", nothing more. The manual read found 4 problems that no scanner reported.
