# Sample company: Fernhollow Bicycle Works

**Fernhollow Bicycle Works** is an invented UK bicycle maker, and every document here is fictional. It uses the reserved
`fernhollow.example` domain. Treat the files as a company's **internal** documents: in private mode only the local model
reads them, and the egress guard keeps their text out of any public search.

The folder is laid out the way the watched-folder inbox expects, `<workspace folder>/<collection>/<file>`, so you can
import everything by pointing the inbox at `examples/inbox`. The same files can also be uploaded by hand on the
**Documents** page.

```text
examples/inbox/fernhollow-bicycle-works/     <- workspace "Fernhollow Bicycle Works"
  Handbook/                                  <- everyone in the workspace
    employee-handbook.md
    it-security-policy.md
    travel-and-expenses.docx
  Engineering/                               <- group "engineering" only
    frame-fatigue-test-procedure.md
    trailhawk-2027-release-checklist.md
    supplier-quality-agreement.pdf
  Finance-Confidential/                      <- group "finance" only
    q3-2026-board-financials.md
    salary-bands-2026.docx
    vendor-contract-summary.pdf
```

## Load it

The inbox never creates workspaces or collections, so create them first, then switch the inbox on.

1. In your env file (`.env` for the dev stack, `.env.private` for the private stack), set:

   ```env
   INBOX_ROOT=/data/inbox
   INBOX_HOST_DIR=./examples/inbox
   INBOX_MOUNT_MODE=ro          # import in place; the worker never moves or changes these tracked files
   SEED_PASSWORD=...            # password for the four logins below (required in the private stack)
   ```

2. Create the company **first**, then start the stack. `run --rm api` starts only the database and the migration, not
   the worker, so the workspace exists before the first scan:

   ```bash
   # private stack
   docker compose -f docker-compose.private.yml --env-file .env.private run --rm api python -m app.seed_example
   docker compose -f docker-compose.private.yml --env-file .env.private up -d
   # development stack
   docker compose run --rm api python -m app.seed_example
   docker compose up -d --build
   ```

3. The worker scans when it starts and then every `INBOX_POLL_SECONDS` (default 30 s); an admin can also press
   **Inbox → Scan now**. The nine files are imported and ingested, and the Documents page shows them as `ready`.

**If the stack was already running** when you created the company, its first scan found no matching workspace. The
**Inbox** page then lists the files as quarantined with "No workspace matches this folder name". A read-only mount can't
move them aside, so they are skipped until they change: give them a new timestamp and they are imported on the next
scan (`find examples/inbox -type f -exec touch {} +` in Git Bash, or
`Get-ChildItem examples\inbox -Recurse -File | % { $_.LastWriteTime = Get-Date }` in PowerShell).

On a CPU-only machine the local model can take minutes per answer. If questions fail with "The local model failed",
raise `LOCAL_LLM_TIMEOUT_S` (seconds per model call, default 180) in your env file and run `up -d` again.

Without Docker (from `backend/`): `uv run python -m app.seed_example --upload ../examples/inbox/fernhollow-bicycle-works`
creates the company and uploads the files directly.

To add your own internal files, copy them into one of the three collection folders (PDF, DOCX or Markdown; up to
`INBOX_MAX_FILE_MB`). The next scan imports them with that folder's audience. With `INBOX_MOUNT_MODE=ro` they stay where
they are, and each one is imported once.

## Logins

| User | Can read |
|---|---|
| `admin@fernhollow.example` | everything (workspace admin) |
| `employee@fernhollow.example` | Handbook |
| `engineer@fernhollow.example` | Handbook, Engineering |
| `finance@fernhollow.example` | Handbook, Finance-Confidential |

## Questions to try

| Question | `employee` | `engineer` | `finance` |
|---|---|---|---|
| How many days of annual leave do employees get? | answered (27 days) | answered | answered |
| What is the hotel limit per night in London? | answered (£180) | answered | answered |
| How many cycles does the frame fatigue test run? | refused | answered (100,000) | refused |
| When is the Trailhawk 2027 public launch? | refused | answered (15 March 2027) | refused |
| What was revenue in Q3 2026? | refused | refused | answered (£8.4 million) |
| What is the salary range for band B3? | refused | refused | answered (£38,000 to £52,000) |

A refusal here is the access control working: a user gets no answer, no citation and no hint about documents they
cannot read.

## Regenerating the binary files

The DOCX and PDF files are built by [make_examples.py](make_examples.py); the Markdown files are edited by hand. After
changing the text in the script: `cd backend && uv run python ../examples/make_examples.py`.
