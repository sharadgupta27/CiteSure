# The CiteSure agent team

CiteSure was built by Claude Code acting as a **tech lead** that planned each phase and delegated parts to sub-agents, with a human owner reviewing. The full log is in [docs/ai-workflow.md](../docs/ai-workflow.md).

This folder turns the roles played during that build into **reusable Claude Code subagents**. Each role has a mission, the files it owns, what it built, its rules and its definition of done. You can rebuild a phase or extend CiteSure with the same division of work.

| Agent | Role | Phases ([plan.md](../plan.md)) | Edits code |
|---|---|---|---|
| [tech-lead](tech-lead.md) | Plans, splits work by file ownership, delegates, integrates, runs full checks | all | yes |
| [eval-engineer](eval-engineer.md) | Golden set first, eval harness, experiment matrix, EvalOps export | 0, 5 | yes |
| [api-designer](api-designer.md) | `openapi.yaml`, Spectral, generated client, drift test | 1 | yes |
| [frontend-engineer](frontend-engineer.md) | React UI, citation and PDF viewers, admin pages | 1, 13 | yes |
| [backend-engineer](backend-engineer.md) | Auth, ACL, workspaces, uploads, audit, OIDC, vault, migrations | 2, 13 | yes |
| [rag-engineer](rag-engineer.md) | Parsing, chunking, hybrid retrieval, rerank, generation, verification, worker | 3, 4, 13 | yes |
| [privacy-engineer](privacy-engineer.md) | Private mode: egress guard and client, research connectors, allow-list proxy | 12 | yes |
| [qa-engineer](qa-engineer.md) | Integration, ACL leak, prompt-injection and E2E tests | 6 | tests only |
| [devops-engineer](devops-engineer.md) | Docker, compose, CI/CD, observability, hosting | 7, 8 | yes |
| [agent-pack-engineer](agent-pack-engineer.md) | Skills, subagents, MCP server, hooks, plugin, nightly agent | 9 | yes |
| [security-reviewer](security-reviewer.md) | Scanners, threat model, independent review | 10 | no (findings only) |
| [docs-writer](docs-writer.md) | README, docs, Substack series | 11 | docs only |

## How the team works

```text
owner ──goal──▶ tech-lead ──▶ eval-engineer      (1. the questions that decide success)
                    │     ──▶ api-designer       (2. the contract)
                    │     ──▶ backend / rag / frontend / privacy engineers   (3. code, by file ownership)
                    │     ──▶ qa-engineer        (4. tests that prove it, including leak tests)
                    │     ──▶ security-reviewer  (5. independent review of ACL, auth, egress, uploads)
                    │     ──▶ devops-engineer    (6. images, CI, observability)
                    └───▶ docs-writer            (7. README, docs, Substack chapter)
owner ◀──diff, test output, eval table── tech-lead     (the owner reviews and commits)
```

Rules every agent follows: the non-negotiables in [CLAUDE.md](../CLAUDE.md), no commits or deploys without the owner, and no shared file edited by two agents at once.

## How these differ from `agent-capabilities/`

| | `agent-team/` (this folder) | `agent-capabilities/subagents/` |
|---|---|---|
| Purpose | **build and extend** CiteSure | **operate and debug** a running CiteSure |
| Access | the repository | the MCP server as a scoped service user |
| Examples | `rag-engineer`, `qa-engineer` | `retrieval-debugger`, `citation-auditor` |

## Use them

The canonical files live here. `python agent-hooks/install.py` copies them to `.claude/agents/`, where Claude Code picks them up; `--check` (run by the tests) fails when a copy is out of date. Then, in Claude Code:

```text
Use the tech-lead agent to plan adding a PowerPoint parser, then delegate it.
Use the security-reviewer agent to review the diff of backend/app/services/acl.py.
```

The team is not part of the shareable plugin: the plugin is for people who **use** CiteSure, the team is for people who **develop** it.
