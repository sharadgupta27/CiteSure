# Publishing notes for the Substack series

Fourteen chapters, an index and a glossary, all in Markdown. Substack's editor accepts pasted rich text but not Markdown files directly, so use one of the two routes below.

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

Chapter 2 has no image. Screenshots were captured from the running app with `SCREENSHOTS=1 npx playwright test screenshots grafana-shot` in `e2e/`. Some screenshots (for example `09-quality-compare.png`) were taken while other evaluation runs existed in the database, so their history lists look busier than a fresh install; re-capture on a clean database if that bothers you.

## Suggested posting plan

| Week | Chapters | Hook |
|---|---|---|
| 1 | Index + 1, 2 | "I wrote the exam before the student" |
| 2 | 3, 4, 5 | "The most common RAG security bug" and real search failures |
| 3 | 6, 7 | "How to catch an AI lying, with code" and the scoreboard |
| 4 | 8, 9 | A UI people trust; testing a non-deterministic system |
| 5 | 10, 11 | Shipping honestly; monitoring "up but wrong" |
| 6 | 12, 13, 14 | Agent guardrails; the threat model; lessons |

Each chapter stands alone, so readers can join at any point. End every post with the "Try it yourself" section; it gives readers something to do and to reply about.

## Before you publish: five checks

1. **Do not claim a live demo.** The series says plainly that nothing was deployed. If you deploy it, update chapters 10 and 14.
2. **Do not quote real-model quality numbers** unless you have run the real-model evaluation and replaced the table in `docs/eval-results.md`.
3. Re-run the commands shown (`docker compose up`, the evaluation, the tests) on your machine and fix any number that has drifted (test counts in chapters 9 and 14).
4. Read `security/ai-pr-audit.md` yourself and fill in the countersignature table before describing the security work as reviewed.
5. Replace the "Next:" links with real URLs.
