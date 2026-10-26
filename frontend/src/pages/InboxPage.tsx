import { useState } from "react";
import { useInboxItems, useInboxStatus, useRequestInboxScan, type InboxFolder, type InboxItem, type InboxItemStatus } from "../api/hooksInbox";
import { useWorkspace } from "../auth/WorkspaceContext";
import { Button, Card, Empty, ErrorBanner, Spinner } from "../components/ui";

const FILTERS: { value: InboxItemStatus | undefined; label: string }[] = [
  { value: undefined, label: "All" },
  { value: "imported", label: "Imported" },
  { value: "quarantined", label: "Quarantined" },
  { value: "failed", label: "Failed" },
  { value: "duplicate", label: "Duplicates" },
];

const STATUS_PILL: Record<InboxItemStatus, string> = {
  imported: "bg-emerald-100 text-emerald-800",
  duplicate: "bg-slate-100 text-slate-700",
  quarantined: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-800",
};

function formatTime(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : "never";
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function InboxPage() {
  const { current } = useWorkspace();
  const workspaceId = current?.id;
  const status = useInboxStatus(workspaceId);
  const [filter, setFilter] = useState<InboxItemStatus | undefined>(undefined);
  const items = useInboxItems(workspaceId, filter);
  const scan = useRequestInboxScan(workspaceId ?? "");

  const data = status.data;
  const quarantined = data?.folders.reduce((n, f) => n + f.quarantined, 0) ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Watched folders</h1>
        {data?.enabled && (
          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-500" aria-live="polite">
              {data.scan_requested ? "Scan requested, waiting for the worker…" : `Last scan: ${formatTime(data.last_scan_at)}`}
            </span>
            <Button variant="secondary" onClick={() => scan.mutate()} disabled={scan.isPending || data.scan_requested}>
              Scan now
            </Button>
          </div>
        )}
      </div>

      <ErrorBanner error={status.error ?? scan.error} />
      {status.isLoading && <Spinner label="Loading…" />}

      {data && !data.enabled && (
        <Empty>
          The watched-folder inbox is switched off. An administrator turns it on by setting <code>INBOX_ROOT</code> to a folder
          the worker can read.
        </Empty>
      )}

      {data?.enabled && (
        <>
          <Card title="How it works">
            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
              <li>
                Drop files into <code className="rounded bg-slate-100 px-1">{data.workspace_folder}/&lt;collection name&gt;/</code> on
                the server. The folder name picks the collection, and the collection decides who can read the file.
              </li>
              <li>
                Accepted: {data.allowed_types.join(", ") || "nothing"} (checked by content, not by name), up to {data.max_file_mb} MB.
                The worker looks every {data.poll_seconds} seconds.
              </li>
              <li>
                A file in a folder that matches no collection is <strong>quarantined</strong> and never imported. Fix the folder name or
                create the collection, then move the file back from <code className="rounded bg-slate-100 px-1">.quarantine</code>.
              </li>
            </ul>
          </Card>

          {quarantined > 0 && (
            <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {quarantined} {quarantined === 1 ? "file was" : "files were"} quarantined because no matching collection was found.
            </div>
          )}

          <Card title="Folders">
            {data.folders.length === 0 ? <Empty>No collections yet, so there is nothing to watch.</Empty> : <FolderTable folders={data.folders} />}
          </Card>

          <Card title="Recent files">
            <div role="group" aria-label="Filter by status" className="mb-3 flex flex-wrap gap-2">
              {FILTERS.map((f) => (
                <button
                  key={f.label}
                  type="button"
                  aria-pressed={f.value === filter}
                  onClick={() => setFilter(f.value)}
                  className={`rounded-full border px-3 py-1 text-sm font-medium transition-colors ${f.value === filter ? "border-indigo-300 bg-indigo-50 text-indigo-800" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"}`}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <ErrorBanner error={items.error} />
            {items.isLoading && <Spinner />}
            {items.data && items.data.length === 0 && <Empty>No files here yet.</Empty>}
            {items.data && items.data.length > 0 && <ItemTable items={items.data} />}
          </Card>
        </>
      )}
    </div>
  );
}

function FolderTable({ folders }: { folders: InboxFolder[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Watched folders and what happened to their files</caption>
        <thead className="text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="py-2 pr-4">Folder</th>
            <th scope="col" className="py-2 pr-4">Imported</th>
            <th scope="col" className="py-2 pr-4">Duplicates</th>
            <th scope="col" className="py-2 pr-4">Quarantined</th>
            <th scope="col" className="py-2 pr-4">Failed</th>
            <th scope="col" className="py-2">Last activity</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {folders.map((f) => (
            <tr key={`${f.collection_id ?? "none"}:${f.folder}`}>
              <th scope="row" className="py-2 pr-4 font-medium text-slate-800">
                <code>{f.folder || "(inbox root)"}</code>
                {!f.matched && <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">no matching collection</span>}
              </th>
              <td className="py-2 pr-4">{f.imported}</td>
              <td className="py-2 pr-4">{f.duplicates}</td>
              <td className="py-2 pr-4">{f.quarantined}</td>
              <td className="py-2 pr-4">{f.failed}</td>
              <td className="py-2 text-slate-500">{formatTime(f.last_activity_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ItemTable({ items }: { items: InboxItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Files the watcher has looked at, newest first</caption>
        <thead className="text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="py-2 pr-4">File</th>
            <th scope="col" className="py-2 pr-4">Status</th>
            <th scope="col" className="py-2 pr-4">Collection</th>
            <th scope="col" className="py-2 pr-4">Size</th>
            <th scope="col" className="py-2">When</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((item) => (
            <tr key={item.id} className="align-top">
              <td className="py-2 pr-4">
                <div className="font-medium text-slate-800">{item.filename}</div>
                <div className="text-xs text-slate-500">
                  <code>{item.folder || "(inbox root)"}</code>
                </div>
                {item.reason && <div className="mt-1 text-xs text-slate-600">{item.reason}</div>}
              </td>
              <td className="py-2 pr-4">
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_PILL[item.status]}`}>{item.status}</span>
                {item.document_status && <div className="mt-1 text-xs text-slate-500">document: {item.document_status}</div>}
              </td>
              <td className="py-2 pr-4">{item.collection_name ?? <span className="text-slate-400">none</span>}</td>
              <td className="py-2 pr-4 whitespace-nowrap">{formatSize(item.size_bytes)}</td>
              <td className="py-2 whitespace-nowrap text-slate-500">{formatTime(item.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
