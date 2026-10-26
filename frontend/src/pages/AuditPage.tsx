import { useState, type FormEvent } from "react";
import { AUDIT_PAGE_SIZE, downloadAuditCsv, useAuditEvents, useVerifyAuditChain, type AuditFilters } from "../api/hooksAdmin";
import { useWorkspace } from "../auth/WorkspaceContext";
import { Button, Card, Empty, ErrorBanner, Field, Spinner, inputClass } from "../components/ui";

/** The actions the server records (services/audit.py). The filter sends the exact string. */
const ACTIONS = [
  "auth.login",
  "auth.login_failed",
  "auth.register",
  "auth.oidc_login",
  "auth.oidc_failed",
  "workspace.create",
  "member.add",
  "group.create",
  "group.member_add",
  "collection.create",
  "collection.update",
  "collection.delete",
  "document.upload",
  "document.delete",
  "document.reindex",
  "ask",
  "feedback.create",
  "golden.create",
  "golden.update",
  "golden.delete",
  "golden.promote",
  "eval.run",
  "audit.export",
];

interface Draft {
  actor: string;
  action: string;
  since: string;
  until: string;
}
const EMPTY: Draft = { actor: "", action: "", since: "", until: "" };

/** The date inputs are local dates; `until` is made exclusive by moving to the start of the next day. */
export function toFilters(draft: Draft): AuditFilters {
  const filters: AuditFilters = {};
  if (draft.actor.trim()) filters.actor = draft.actor.trim();
  if (draft.action) filters.action = draft.action;
  if (draft.since) filters.since = new Date(`${draft.since}T00:00:00`).toISOString();
  if (draft.until) {
    const end = new Date(`${draft.until}T00:00:00`);
    end.setDate(end.getDate() + 1);
    filters.until = end.toISOString();
  }
  return filters;
}

function compact(metadata: Record<string, unknown>): string {
  const text = Object.entries(metadata)
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" ");
  return text.length > 140 ? `${text.slice(0, 139)}…` : text;
}

export function AuditPage() {
  const { current } = useWorkspace();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [filters, setFilters] = useState<AuditFilters>({});
  const [offset, setOffset] = useState(0);
  const query = useAuditEvents(current?.id, filters, offset);
  const verify = useVerifyAuditChain(current?.id);
  const [exportError, setExportError] = useState<unknown>(null);
  const page = query.data;

  function apply(event: FormEvent) {
    event.preventDefault();
    setOffset(0);
    setFilters(toFilters(draft));
  }

  function reset() {
    setDraft(EMPTY);
    setOffset(0);
    setFilters({});
  }

  async function exportCsv() {
    if (!current) return;
    setExportError(null);
    try {
      const blob = await downloadAuditCsv(current.id, filters);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "audit-log.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(e);
    }
  }

  const from = page && page.total > 0 ? page.offset + 1 : 0;
  const to = page ? page.offset + page.items.length : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Audit log</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Who did what, and when. Entries hold ids, counts and hashes only: never document text or question text. Each entry is chained to the one before it, so a
          changed or removed entry shows up when you verify the chain.
        </p>
      </div>

      <Card title="Chain check" actions={<Button variant="secondary" onClick={() => verify.mutate()} disabled={verify.isPending}>Verify chain</Button>}>
        <ErrorBanner error={verify.error} />
        {verify.isPending && <Spinner label="Checking every entry…" />}
        {verify.data?.ok && (
          <p role="status" className="text-sm text-emerald-700">
            The chain is intact: {verify.data.checked} entries checked
            {verify.data.starts_at_seq && verify.data.starts_at_seq > 1 ? `, starting at #${verify.data.starts_at_seq} (older entries were removed by an operator)` : ""}.
            Latest entry #{verify.data.head_seq}, hash <code className="break-all text-xs">{verify.data.head_hash}</code>. Keep a copy of that hash elsewhere to also detect
            removal of the newest entries.
          </p>
        )}
        {verify.data && !verify.data.ok && (
          <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            The chain is broken at entry #{verify.data.first_bad_seq}: {verify.data.reason}. Treat the log as tampered with from that entry on.
          </p>
        )}
      </Card>

      <Card>
        <form onSubmit={apply} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 lg:items-end">
          <Field label="Person (e-mail or id)">
            <input className={inputClass} value={draft.actor} onChange={(e) => setDraft({ ...draft, actor: e.target.value })} />
          </Field>
          <Field label="Action">
            <select className={inputClass} value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })}>
              <option value="">Any action</option>
              {ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </Field>
          <Field label="From">
            <input className={inputClass} type="date" value={draft.since} onChange={(e) => setDraft({ ...draft, since: e.target.value })} />
          </Field>
          <Field label="To (inclusive)">
            <input className={inputClass} type="date" value={draft.until} onChange={(e) => setDraft({ ...draft, until: e.target.value })} />
          </Field>
          <div className="flex gap-2">
            <Button type="submit">Filter</Button>
            <Button type="button" variant="ghost" onClick={reset}>
              Clear
            </Button>
          </div>
        </form>
      </Card>

      <Card
        title="Entries"
        actions={
          <Button variant="secondary" onClick={exportCsv} disabled={!page || page.total === 0}>
            Export CSV
          </Button>
        }
      >
        <ErrorBanner error={query.error} />
        <ErrorBanner error={exportError} />
        {query.isLoading && <Spinner />}
        {page && page.items.length === 0 && <Empty>No entries match.</Empty>}
        {page && page.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Audit log entries, newest first</caption>
              <thead className="text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="py-2 pr-3">#</th>
                  <th scope="col" className="py-2 pr-3">When</th>
                  <th scope="col" className="py-2 pr-3">Who</th>
                  <th scope="col" className="py-2 pr-3">Action</th>
                  <th scope="col" className="py-2 pr-3">Target</th>
                  <th scope="col" className="py-2">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 align-top">
                {page.items.map((e) => (
                  <tr key={e.seq}>
                    <td className="py-2 pr-3 tabular-nums text-slate-500">{e.seq}</td>
                    <td className="whitespace-nowrap py-2 pr-3">{new Date(e.created_at).toLocaleString()}</td>
                    <td className="py-2 pr-3">{e.actor_email ?? <span className="text-slate-400">unknown</span>}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{e.action}</td>
                    <td className="max-w-[16rem] truncate py-2 pr-3 font-mono text-xs text-slate-600" title={e.target ?? undefined}>
                      {e.target ?? ""}
                    </td>
                    <td className="py-2 font-mono text-xs text-slate-600">{compact(e.metadata)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {page && page.total > 0 && (
          <div className="mt-4 flex items-center justify-between text-sm text-slate-600">
            <span>
              {from} to {to} of {page.total}
            </span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - AUDIT_PAGE_SIZE))}>
                Newer
              </Button>
              <Button variant="secondary" disabled={to >= page.total} onClick={() => setOffset(offset + AUDIT_PAGE_SIZE)}>
                Older
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
