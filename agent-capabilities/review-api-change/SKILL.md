---
name: review-api-change
description: Make and review a change to the CiteSure HTTP API in the right order (contract first), with an independent review. Use whenever openapi.yaml, backend/app/api, backend/app/schemas or frontend/src/api would change, or when someone asks to add or modify an endpoint or response field.
---

# Review (and make) an API change

The contract is `openapi.yaml`. The frontend client is generated from it; the backend must match it; a drift test fails when they disagree.

## Steps

1. **State the change** in 2-4 bullets: the endpoint, who may call it, what content it returns, which roles, which errors.
2. **Contract first.** Edit `openapi.yaml`. Then `npx @stoplight/spectral-cli@6 lint openapi.yaml` (must be clean).
3. **Generate the client**: `cd frontend && npm run gen:api`. Never hand-edit `src/api/schema.d.ts` (the hook blocks it).
4. **Backend**: update `backend/app/schemas/api.py` (same names and fields), the router (set `operation_id` to match), then the service.
   Keep layering: router -> service -> repository.
5. **Check agreement**: `cd backend && uv run pytest tests/unit/test_contract.py` (drift test), then `cd ../frontend && npm run typecheck`.
6. **Security review**. If the endpoint returns document content, chunks, citations, files or retrieval diagnostics, it MUST:
   filter by `acl.allowed_collection_ids` inside the SQL, answer 404 (not 403) for things the caller may not read, and have a leak test in
   `backend/tests/integration/test_acl_leaks.py`. Update `docs/permissions.md` if roles change.
7. **Independent review**: invoke the `api-contract-reviewer` subagent on the diff. It is read-only and returns BLOCKING / NON-BLOCKING findings.
   Fix every blocking finding.
8. **Tests and log**: unit + integration tests for the endpoint, `docs/ai-workflow.md` entry, then show the human the final diff.

## Rules of thumb

- Additive changes are safe. Renaming, removing, making optional fields required or narrowing an enum is a breaking change: call it out.
- Every operation documents its realistic errors (401, 404, 409, 413, 422, 429) with the shared `Error` schema.
- Lists return arrays; timestamps are `date-time`; ids are `uuid`; field names are `snake_case`.
- New admin-only endpoints say so in the summary and in `docs/permissions.md`.
