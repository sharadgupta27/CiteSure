import { useState } from "react";
import { useDashboard } from "../api/hooksAdmin";
import { useWorkspace } from "../auth/WorkspaceContext";
import { DayBarChart, HBars, Tile, VizStyles } from "../components/charts";
import { Badge, Card, ErrorBanner, Spinner, inputClass } from "../components/ui";
import { formatCount, formatMs, formatPercent, formatUsd } from "../lib/charts";

const RANGES = [7, 30, 90] as const;

export function DashboardPage() {
  const { current } = useWorkspace();
  const [days, setDays] = useState<number>(30);
  const query = useDashboard(current?.id, days);
  const board = query.data;

  return (
    <div className="space-y-6">
      <VizStyles />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Dashboard</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600">
            How the system is doing in {current?.name ?? "this workspace"}: counts, rates and timings only. No question or document text is shown here.
          </p>
        </div>
        <label className="text-sm">
          <span className="mb-1 block font-medium text-slate-700">Period</span>
          <select className={inputClass} value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {RANGES.map((r) => (
              <option key={r} value={r}>
                Last {r} days
              </option>
            ))}
          </select>
        </label>
      </div>

      <ErrorBanner error={query.error} />
      {query.isLoading && <Spinner label="Loading the numbers…" />}

      {board && (
        <>
          <section aria-label="Key numbers" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Tile label="Questions" value={formatCount(board.questions.total)} hint={`${board.questions.answered} answered, ${board.questions.refused} refused`} />
            <Tile label="Refusal rate" value={formatPercent(board.questions.refusal_rate)} hint="Questions the sources could not support" />
            <Tile
              label="Dropped-claim rate"
              value={formatPercent(board.questions.dropped_claim_rate)}
              hint={`${board.questions.claims_dropped} dropped, ${board.questions.claims_shown} shown`}
            />
            <Tile label="Latency p50 / p95" value={`${formatMs(board.latency.p50_ms)} / ${formatMs(board.latency.p95_ms)}`} hint="Whole answer, all stages" />
            <Tile label="Cost" value={formatUsd(board.cost.total_usd)} hint={`${formatUsd(board.cost.per_question_usd)} per question`} />
            <Tile label="Tokens" value={`${formatCount(board.cost.tokens_in)} in`} hint={`${formatCount(board.cost.tokens_out)} out`} />
            <Tile label="Documents" value={formatCount(board.documents.total)} hint={`${formatCount(board.documents.chunks)} chunks`} />
            <Tile
              label="Feedback"
              value={board.feedback.positive_ratio === null ? "n/a" : formatPercent(board.feedback.positive_ratio)}
              hint={`${board.feedback.up} helpful, ${board.feedback.down} not helpful`}
            />
          </section>

          <Card>
            <DayBarChart days={board.per_day} />
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <HBars
                title="Documents by status"
                unit="Documents"
                empty="No documents yet."
                rows={board.documents.by_status.map((s) => ({ label: s.label, value: s.count }))}
              />
            </Card>
            <Card>
              <HBars
                title="Outbound requests to public sources"
                unit="Requests"
                empty="Nothing left the system in this period."
                rows={board.egress.map((e) => ({ label: `${e.destination} (${e.status})`, value: e.count }))}
              />
            </Card>
          </div>

          <Card title="Ingestion failures">
            <p className="mb-3 text-sm text-slate-600">
              {board.ingest.failed_documents} document{board.ingest.failed_documents === 1 ? "" : "s"} failed to ingest, and {board.ingest.failed_jobs} background job
              {board.ingest.failed_jobs === 1 ? "" : "s"} failed in this period.
            </p>
            {board.ingest.recent_failures.length === 0 ? (
              <p className="text-sm text-slate-500">No failed documents.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {board.ingest.recent_failures.map((f) => (
                  <li key={f.document_id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                    <Badge value="failed" />
                    <span className="font-medium text-slate-800">{f.title}</span>
                    <span className="text-slate-500">{f.error ?? "No reason recorded"}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
