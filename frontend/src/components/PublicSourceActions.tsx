import type { Citation } from "../api/client";
import { ApiError } from "../api/client";
import { useActiveWorkspaceId, useFullTextStatus, useRequestFullText } from "../api/hooksFulltext";
import { Button, ErrorBanner, Spinner } from "./ui";

const BUDGET_CODE = "fulltext_budget_exceeded";

/** Actions on a public (published paper) citation: add the open-access full text so the next question can cite its pages. */
export function PublicSourceActions({ citation }: { citation: Citation }) {
  const workspaceId = useActiveWorkspaceId();
  const request = useRequestFullText();
  const status = useFullTextStatus(request.data?.id);
  const current = status.data ?? request.data;
  const address = citation.url ?? "";
  const working = request.isPending || current?.status === "queued" || current?.status === "running";

  const fetchFullText = () => {
    if (workspaceId && address) request.mutate({ workspace_id: workspaceId, url: address });
  };

  return (
    <section aria-label="Full text" className="space-y-2 rounded-md border border-slate-200 p-3" data-testid="fulltext-actions">
      <p className="text-sm text-slate-600">
        Only the abstract is quoted above. If the paper is open access, you can add its full text to this server&rsquo;s public
        cache, so answers can cite its passages with page numbers.
      </p>

      {working ? (
        <Spinner label={current?.status === "running" ? "Downloading and indexing the paper…" : "Waiting for the worker…"} />
      ) : current?.status === "ready" ? (
        <p role="status" className="text-sm font-medium text-emerald-700">
          Full text added: {current.passages ?? 0} passages{current.pages ? ` from ${current.pages} pages` : ""}; ask again to use it.
        </p>
      ) : (
        <Button variant="secondary" onClick={fetchFullText} disabled={!workspaceId || !address}>
          {current?.status === "failed" ? "Try again" : "Fetch full text"}
        </Button>
      )}

      {!address && <p className="text-xs text-slate-500">This citation has no address, so its full text cannot be looked up.</p>}
      {address && !workspaceId && <p className="text-xs text-slate-500">Select a workspace to fetch full text.</p>}

      {current?.status === "failed" && (
        <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {current.message ?? "The full text could not be added."}
        </div>
      )}
      {request.error instanceof ApiError && request.error.code === BUDGET_CODE ? (
        <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" data-testid="fulltext-budget">
          {request.error.message}
        </div>
      ) : (
        <ErrorBanner error={request.error} />
      )}

      {current && current.egress.length > 0 && (
        <p className="text-xs text-slate-500" data-testid="fulltext-egress">
          Contacted: {[...new Set(current.egress.map((record) => record.destination))].join(", ")}. Only the
          paper&rsquo;s public identifier was sent; no question or document text.
        </p>
      )}
      {current && current.status !== "ready" && !working && (
        <p className="text-xs text-slate-500">
          {current.fetches_remaining} full-text download{current.fetches_remaining === 1 ? "" : "s"} left today in this workspace.
        </p>
      )}
    </section>
  );
}
