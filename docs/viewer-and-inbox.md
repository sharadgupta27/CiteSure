# PDF viewer, highlights and the watched-folder inbox (phase 2)

## PDF viewer with highlights and notes

Opening a cited source that is a PDF shows two tabs in the source drawer: **PDF** (the real page) and **Text** (the chunk view
CiteSure always had). Other file types show only the text view.

- **No external loads.** `pdfjs-dist` is bundled by Vite and its worker is emitted as a local asset (`?url` import). The PDF
  bytes come from the authenticated `GET /documents/{id}/file` (bearer token, then an `ArrayBuffer`), so nothing is fetched from a
  CDN or any other host. This keeps private mode intact: company documents never leave the browser's own origin.
- **The cited quote** is located in the page's text layer (tolerant of case, ligatures, hyphenation and line breaks) and outlined in
  amber. If it cannot be found the viewer still jumps to the cited page, says so, and the Text tab stays available.
- **Navigation:** previous/next, "Go to page", zoom in/out/fit; PageUp/PageDown/Home/End when the page area has focus; the page
  indicator is an `aria-live` region.
- **Highlights:** select text, pick a colour (yellow, green, blue, pink, orange), add an optional note, "Save highlight". They
  are listed under "Your highlights" (jump, edit note, delete) and drawn as overlays. Rectangles are stored as fractions of the
  page (`x, y, w, h` in 0..1), so they survive zooming. Selections across pages are not saved.

### Annotation API

| Operation | Route |
|---|---|
| `listAnnotations` | `GET /documents/{document_id}/annotations` |
| `createAnnotation` | `POST /documents/{document_id}/annotations` (PDF documents only; page must exist; 1 to 100 rects; text up to 2000 chars) |
| `updateAnnotation` | `PATCH /annotations/{annotation_id}` (note and colour only) |
| `deleteAnnotation` | `DELETE /annotations/{annotation_id}` |

Access rules (tested in `tests/integration/test_annotations.py`):

- Annotations are **private to their author**: every query filters on `user_id`; another user, even an admin, never sees them.
- A user can annotate only documents they can read (`services/acl.py`). A document they cannot read, a missing document and
  somebody else's annotation all answer **404**, never 403.
- If a user later loses access to a collection, their own highlights on its documents stop being served too (they quote the text).
- Deleting a document or a user deletes the annotations (`ON DELETE CASCADE`).

## Watched-folder inbox

Off by default. Set `INBOX_ROOT` to a folder the **worker** can read and write.

```text
<INBOX_ROOT>/<workspace folder>/<collection name>/<file>
```

- **Workspace folder:** the workspace name as a slug (`Acme Corp` becomes `acme-corp`) when that is unique, otherwise the workspace
  id. The admin page shows the exact name. In a deployment where several unrelated people can create workspaces, use the id.
- **Collection folder:** the collection's name (case-insensitive; a slug match also works). It must match exactly one collection.
- **The folder is the access decision.** The file becomes a document of that collection and gets that collection's rules
  (whole workspace, or only the listed groups). The watcher never creates collections or groups and never picks an audience on its own.

### What happens to a file

| Situation | Result | Where the file goes |
|---|---|---|
| Folder matches no workspace/collection (or several), file not in a collection folder, nested deeper than the collection folder | `quarantined` | `<root>/.quarantine/...` |
| Symlink, or a path that resolves outside the root (also NTFS junctions) | `quarantined`, never opened | left in place |
| Empty, larger than `INBOX_MAX_FILE_MB`, extension not allowed, content not an allowed type (magic bytes via `detect()`), content does not match the extension | `failed` | `<root>/.failed/...` |
| Same sha256 already in the collection | `duplicate` | `<root>/.processed/...` |
| Otherwise | `imported`: blob + `documents` row (`queued`) + ingestion job, exactly like an upload; the normal worker loop parses, chunks and embeds it | `<root>/.processed/...` |

Other details: hidden files, `~$` files and `*.part`/`*.tmp`/`*.crdownload` are ignored. A file must be older than
`INBOX_SETTLE_SECONDS` and unchanged while it is read, so a half-copied file is never imported. If a file cannot be moved (read-only
mount), its path, size and mtime are recorded so it is not imported twice. To retry a quarantined file, fix the folder name or create
the collection, then move it back from `.quarantine` (or touch it if it was left in place). A scan holds a Postgres advisory lock,
so several workers never scan at once. Logs contain ids and counts only: no filenames, no text.

Files whose first folder matches **no workspace** are quarantined on disk but deliberately not shown in any UI: they belong to no
tenant, and showing them to an arbitrary workspace admin would reveal other people's file names.

### Settings

| Variable | Default | Meaning |
|---|---|---|
| `INBOX_ROOT` | empty (off) | Root folder, as seen by the worker |
| `INBOX_POLL_SECONDS` | 30 | Scan interval (an admin can also press "Scan now") |
| `INBOX_SETTLE_SECONDS` | 5 | Minimum file age before import |
| `INBOX_MAX_FILE_MB` | 20 | Largest file |
| `INBOX_ALLOWED_TYPES` | `pdf,docx,markdown` | Detected kinds (also `html`); unknown names are ignored |

Private deployment: `docker-compose.private.yml` mounts `${INBOX_HOST_DIR:-./inbox}` at `/data/inbox` in the worker; set
`INBOX_ROOT=/data/inbox` to switch it on. The folder must be writable by the container user (the worker moves files). The watcher
only reads local disk and uses the same local embedding and storage as uploads, so nothing leaves the machine.

### Admin API and page

`getInboxStatus`, `listInboxItems`, `requestInboxScan` under `/workspaces/{workspace_id}/inbox` (workspace admins only: members get
403, non-members 404). The **Inbox** page shows the folder to use, per-folder counts (folders matching no collection are flagged),
recent files with the reason for each quarantine or failure, a status filter and "Scan now". The worker runs the scan
(`app/worker/inbox_watcher.py`, started next to the job loop in `python -m app.worker`); "Scan now" only sets a flag in `inbox_state`.

### Not done / known limits

- Scans are driven by polling, not file-system events.
- No sidecar metadata files (`.json`), no per-file group override: use another collection.
- Audit entries exist for creating and deleting a highlight and for "Scan now" (`annotation.create`, `annotation.delete`, `inbox.scan_requested`), not for editing a note or for each imported file.

### Deployment note: serve `.mjs` as JavaScript

The PDF.js worker is an ES module (`pdf.worker.min-*.mjs`). nginx's stock `mime.types` has no entry for `.mjs` and would send
`application/octet-stream`, which browsers refuse to run as a module; the viewer then shows "The PDF could not be displayed".
`frontend/nginx.conf` maps `mjs` to `text/javascript`. If you put the app behind another web server or a CDN, make sure it does
the same (check the response header of `/assets/pdf.worker.min-*.mjs`). The same file makes nginx re-resolve the `api` name every
few seconds, so recreating the API container does not leave the frontend pointing at a dead address.
