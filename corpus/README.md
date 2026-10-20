# Corpus

CiteSure needs documents to answer questions about. This folder holds two corpora.

## `demo/` (committed, used by tests, evals and the seed script)

A **fictional** company handbook for "Acme Robotics", written for this project, so it is free of third-party licenses (MIT, same as the repo).

| Collection | Folder | Who can read it | Documents |
|---|---|---|---|
| `General` | `demo/general/` | every workspace member | 16 policy pages (Markdown + one HTML page) |
| `People-Ops-Confidential` | `demo/people-ops-confidential/` | members of the `hr` group (and workspace admins) | 4 restricted HR documents |

Every fact in the golden question set (`backend/evals/golden.jsonl`) is quoted from these files. Run `python corpus/validate_golden.py` to check that each expected quote still exists verbatim.

## `fetch_gitlab_handbook.py` (optional, a bigger stress test)

The [GitLab Handbook](https://handbook.gitlab.com/) is real, large and messy. It is published under **CC BY-SA 4.0** (see <https://handbook.gitlab.com/handbook/about/> and the repository `LICENSE`). Because that license requires attribution and share-alike, we do **not** commit the pages. The script downloads a few hundred Markdown pages into `corpus/raw/` (git-ignored):

```bash
uv run --no-project --with httpx python corpus/fetch_gitlab_handbook.py --limit 200
```

If you ship a public demo with those pages, add the attribution required by CC BY-SA 4.0.

## Swapping in your own domain

Only two things change: the files in a corpus folder and the golden set. Nothing in the code depends on the Acme content.
