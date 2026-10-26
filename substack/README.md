# Publishing notes for the Substack series

Sixteen chapters, an index and a glossary, all in Markdown. Substack's editor accepts pasted rich text but not Markdown files directly, so use one of the two routes below.

## Route A: paste into the editor

1. Open the chapter in a Markdown previewer (VS Code: "Markdown: Open Preview"), select all, copy, paste into a new Substack post.
2. **Images do not carry over.** Upload each PNG listed in the chapter (the `![...](images/...)` lines) with the editor's image button, at the position of the placeholder.
3. Tables paste as tables. Check them on mobile; wide tables may need to be split.
4. Code blocks paste as code blocks. Check that indentation survived.

## Route B: convert to HTML first

`pandoc substack/01-start-with-the-eval-set.md -o 01.html` then paste the HTML into Substack's "Import" or HTML-capable field. Upload images manually either way.

## Things Substack does **not** render

- **Mermaid and SVG diagrams.** That is why every figure here is a PNG (`images/fig-*.png`). If you edit a figure, regenerate with `python substack/figures/make_figures.py` (needs `matplotlib`).
- Relative links between chapters (`01-...md`). Replace them with the published post URLs once the posts exist, or remove the "Next:" lines.
- Footnotes and collapsible sections.

## Image checklist (every file referenced by the chapters, in `substack/images/`)

| Chapter | Images |
|---|---|
| index | `02-answer-with-citations.png` |
| 1 | `fig-07-architecture.png`, `fig-01-pipeline.png` |
| 3 | `fig-02-acl-prefilter.png`, `04-refusal-for-restricted-question.png`, `06-hr-answer-from-confidential.png`, `05-employee-documents-no-confidential.png` |
| 4 | `fig-03-chunking.png`, `07-admin-documents.png` |
| 5 | `fig-04-rrf.png` |
| 6 | `fig-05-verification.png` |
| 7 | `fig-06-results.png` |
| 8 | `02-answer-with-citations.png`, `03-source-viewer-highlight.png`, `04-refusal-for-restricted-question.png`, `01-login.png`, `08-workspace-access-control.png`, `09-quality-compare.png`, `10-feedback-comment.png`, `11-feedback-queue.png` |
| 9 | `fig-08-test-pyramid.png` |
| 10 | `fig-12-deployment.png` |
| 11 | `12-grafana-dashboard.png` |
| 12 | `fig-09-agent-pack.png`, `fig-10-hook.png` |
| 13 | `fig-11-threats.png` |
| 14 | `fig-06-results.png` |
| 15 | none |
| 16 | `13-answer-from-pdf.png`, `14-pdf-viewer-citation.png`, `18-inbox-watched-folders.png`, `12-research-scope-preview.png`, `15-learn-overview.png`, `16-study-set.png`, `17-learning-plan.png`, `19-admin-dashboard.png`, `20-audit-log.png` |

Chapter 2 has no image. Screenshots `01`-`11` and `13`-`20` were captured by `e2e/tests/screenshots.spec.ts` from a freshly seeded demo stack (fake models, so they are deterministic and cost nothing). `12-grafana-dashboard.png` comes from the monitoring stack (`grafana-shot.spec.ts`) and was not retaken.

To recapture them, start a throw-away copy of the demo stack **with an empty env file** (Compose reads the `.env` in the project folder automatically, and you do not want your real settings or models in a screenshot), seed it, upload a small PDF, then run the script:

```bash
docker compose -p citesure-shots --env-file empty.env up -d --build --wait
docker compose -p citesure-shots --env-file empty.env run --rm api python -m app.seed
cd e2e && SCREENSHOTS=1 npx playwright test screenshots
```

The merged-feature shots (`13`-`20`) expect, in the demo workspace: a PDF titled "Visitor And Badge Policy" in the `General` collection, a study set called "Week one: joining Acme", a learning plan called "Onboarding in two weeks", and two files in the watched folder (`INBOX_ROOT` set on the api and worker). Without them the script fails on the first missing element, which is the signal to set them up.

## Suggested posting plan

| Week | Chapters | Hook |
|---|---|---|
| 1 | Index + 1, 2 | "I wrote the exam before the student" |
| 2 | 3, 4, 5 | "The most common RAG security bug" and real search failures |
| 3 | 6, 7 | "How to catch an AI lying, with code" and the scoreboard |
| 4 | 8, 9 | A UI people trust; testing a non-deterministic system |
| 5 | 10, 11 | Shipping honestly; monitoring "up but wrong" |
| 6 | 12, 13, 14 | Agent guardrails; the threat model; lessons |
| 7 | 15, 16 | Keeping secrets in while letting research in; merging a second project and running it for real |

Each chapter stands alone, so readers can join at any point. End every post with the "Try it yourself" section; it gives readers something to do and to reply about.

## Before you publish: five checks

1. **Do not claim a live demo.** The series says plainly that nothing was deployed. If you deploy it, update chapters 10 and 14.
2. **Do not quote real-model quality numbers** unless you have run the real-model evaluation and replaced the table in `docs/eval-results.md`.
3. Re-run the commands shown (`docker compose up`, the evaluation, the tests) on your machine and fix any number that has drifted (test counts in chapters 9 and 14).
4. Read `security/ai-pr-audit.md` yourself and fill in the countersignature table before describing the security work as reviewed.
5. Replace the "Next:" links with real URLs.
