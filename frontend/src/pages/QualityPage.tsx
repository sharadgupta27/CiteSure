import { useState, type FormEvent } from "react";
import type { Schemas } from "../api/client";
import { useCompareRuns, useCreateEvalRun, useEvalRuns, useGoldenQuestions } from "../api/hooks";
import { useWorkspace } from "../auth/WorkspaceContext";
import { Badge, Button, Card, Empty, ErrorBanner, Field, Spinner, inputClass } from "../components/ui";
import { METRIC_LABELS, METRIC_ORDER, deltaClass, formatDelta, formatMetric } from "../lib/metrics";

type EvalRun = Schemas["EvalRun"];

export function QualityPage() {
  const { current } = useWorkspace();
  const runs = useEvalRuns(current?.id);
  const golden = useGoldenQuestions(current?.id);
  const [base, setBase] = useState<string>();
  const [head, setHead] = useState<string>();
  const finished = runs.data?.filter((r) => r.status === "done") ?? [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight text-slate-900">Quality</h1>
      <p className="max-w-3xl text-sm text-slate-600">
        Every run asks the {golden.data?.length ?? "…"} golden questions and scores retrieval, citations and refusals. Change a setting, run again, and compare:
        a change is only an improvement if the numbers say so.
      </p>
      {current && <NewRun workspaceId={current.id} />}
      <Card title="Evaluation runs">
        <ErrorBanner error={runs.error} />
        {runs.isLoading && <Spinner />}
        {runs.data?.length === 0 && <Empty>No runs yet. Start one above.</Empty>}
        {runs.data && runs.data.length > 0 && <RunsTable runs={runs.data} />}
      </Card>
      {finished.length >= 2 && (
        <Card title="Compare two runs">
          <div className="mb-3 grid gap-3 sm:grid-cols-2">
            <Field label="Before (base)">
              <RunSelect runs={finished} value={base} onChange={setBase} label="Base run" />
            </Field>
            <Field label="After (head)">
              <RunSelect runs={finished} value={head} onChange={setHead} label="Head run" />
            </Field>
          </div>
          <Comparison base={base} head={head} />
        </Card>
      )}
    </div>
  );
}

function RunSelect({ runs, value, onChange, label }: { runs: EvalRun[]; value?: string; onChange: (id: string) => void; label: string }) {
  return (
    <select className={inputClass} aria-label={label} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      <option value="" disabled>
        Choose a run…
      </option>
      {runs.map((r) => (
        <option key={r.id} value={r.id}>
          {r.name} ({new Date(r.created_at).toLocaleString()})
        </option>
      ))}
    </select>
  );
}

function RunsTable({ runs }: { runs: EvalRun[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="py-2">Run</th>
            <th>Status</th>
            <th>Setup</th>
            {METRIC_ORDER.map((m) => (
              <th key={m} className="px-2 text-right">
                {METRIC_LABELS[m]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {runs.map((run) => (
            <tr key={run.id}>
              <td className="py-2 font-medium text-slate-900">{run.name}</td>
              <td>
                <Badge value={run.status} />
                {run.error && <div className="text-xs text-red-600">{run.error}</div>}
              </td>
              <td className="text-xs text-slate-500">
                {run.config.retrieval_mode}
                {run.config.rerank ? " + rerank" : ""} · top {run.config.top_k}
              </td>
              {METRIC_ORDER.map((m) => (
                <td key={m} className="px-2 text-right tabular-nums">
                  {run.metrics ? formatMetric(run.metrics[m]) : "–"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Comparison({ base, head }: { base?: string; head?: string }) {
  const comparison = useCompareRuns(base, head);
  if (!base || !head) return <Empty>Choose two runs.</Empty>;
  if (base === head) return <Empty>Choose two different runs.</Empty>;
  if (comparison.isLoading) return <Spinner />;
  if (comparison.error) return <ErrorBanner error={comparison.error} />;
  const data = comparison.data;
  if (!data?.base.metrics || !data.head.metrics) return null;
  const { base: b, head: h, deltas } = data;
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th className="py-2">Metric</th>
          <th className="text-right">{b.name}</th>
          <th className="text-right">{h.name}</th>
          <th className="text-right">Change</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {METRIC_ORDER.map((metric) => {
          const delta = deltas[metric] ?? 0;
          return (
            <tr key={metric}>
              <td className="py-1.5">{METRIC_LABELS[metric]}</td>
              <td className="text-right tabular-nums">{formatMetric(b.metrics?.[metric])}</td>
              <td className="text-right tabular-nums">{formatMetric(h.metrics?.[metric])}</td>
              <td className={`text-right tabular-nums font-medium ${deltaClass(metric, delta)}`}>{formatDelta(delta)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function NewRun({ workspaceId }: { workspaceId: string }) {
  const create = useCreateEvalRun(workspaceId);
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"hybrid" | "vector">("hybrid");
  const [rerank, setRerank] = useState(true);
  const [topK, setTopK] = useState(6);

  function submit(event: FormEvent) {
    event.preventDefault();
    const label = name.trim() || `${mode}${rerank ? "+rerank" : ""}`;
    create.mutate({ name: label, config: { retrieval_mode: mode, rerank, candidate_k: 30, top_k: topK } }, { onSuccess: () => setName("") });
  }

  return (
    <Card title="Run the evaluation suite">
      <form onSubmit={submit} className="grid items-end gap-3 sm:grid-cols-[1fr_auto_auto_auto_auto]">
        <Field label="Name (optional)">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="hybrid + rerank" />
        </Field>
        <Field label="Retrieval">
          <select className={inputClass} value={mode} onChange={(e) => setMode(e.target.value as "hybrid" | "vector")}>
            <option value="hybrid">hybrid (vector + keyword)</option>
            <option value="vector">vector only</option>
          </select>
        </Field>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} /> Rerank
        </label>
        <Field label="Top K">
          <input className={`${inputClass} w-20`} type="number" min={1} max={20} value={topK} onChange={(e) => setTopK(Number(e.target.value))} />
        </Field>
        <Button type="submit" disabled={create.isPending}>
          Start run
        </Button>
      </form>
      <ErrorBanner error={create.error} />
    </Card>
  );
}
