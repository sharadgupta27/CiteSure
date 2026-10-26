import { useState, type FormEvent } from "react";
import type { Answer, Citation } from "../../api/client";
import { useCompare, useSummarize } from "../../api/hooksLearning";
import { AnswerView } from "../AnswerView";
import { SourceViewer } from "../SourceViewer";
import { Button, Card, ErrorBanner, Field, Spinner, inputClass } from "../ui";
import { DocumentPicker, type PickedDocument } from "./DocumentPicker";

type Tab = "summarize" | "compare";
const MIN_COMPARE = 2;
const MAX_COMPARE = 5;

/** Summarize one document or compare 2-5 on an aspect. Results are ordinary verified answers. */
export function AgentLauncher({ workspaceId }: { workspaceId: string }) {
  const summarize = useSummarize(workspaceId);
  const compare = useCompare(workspaceId);
  const [tab, setTab] = useState<Tab>("summarize");
  const [picked, setPicked] = useState<PickedDocument[]>([]);
  const [focus, setFocus] = useState("");
  const [aspect, setAspect] = useState("");
  const [result, setResult] = useState<Answer | null>(null);
  const [source, setSource] = useState<Citation | null>(null);

  const active = tab === "summarize" ? summarize : compare;
  const canRun =
    tab === "summarize"
      ? picked.length === 1 && (focus.trim() === "" || focus.trim().length >= 3)
      : picked.length >= MIN_COMPARE && picked.length <= MAX_COMPARE && aspect.trim().length >= 3;

  function switchTab(next: Tab) {
    setTab(next);
    setPicked([]);
    setResult(null);
  }

  function run(event: FormEvent) {
    event.preventDefault();
    if (!canRun) return;
    setResult(null);
    const onSuccess = (answer: Answer) => setResult(answer);
    const first = picked[0];
    if (tab === "summarize" && first) {
      summarize.mutate({ document_id: first.id, focus: focus.trim() || null }, { onSuccess });
    } else {
      compare.mutate({ document_ids: picked.map((d) => d.id), aspect: aspect.trim() }, { onSuccess });
    }
  }

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Tool" className="inline-flex rounded-xl border border-slate-200 bg-white p-1">
        {(["summarize", "compare"] as const).map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => switchTab(id)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium ${tab === id ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-100"}`}
          >
            {id === "summarize" ? "Summarize" : "Compare"}
          </button>
        ))}
      </div>

      <Card title={tab === "summarize" ? "Summarize a document" : "Compare documents"}>
        <form onSubmit={run} className="space-y-4">
          <DocumentPicker
            key={tab}
            workspaceId={workspaceId}
            legend={tab === "summarize" ? "Document to summarize" : `Documents to compare (${MIN_COMPARE} to ${MAX_COMPARE})`}
            selected={picked}
            onChange={setPicked}
            max={tab === "summarize" ? 1 : MAX_COMPARE}
          />
          {tab === "summarize" ? (
            <Field label="Focus (optional)">
              <input className={inputClass} value={focus} maxLength={300} placeholder="e.g. security requirements" onChange={(e) => setFocus(e.target.value)} />
            </Field>
          ) : (
            <>
              <Field label="Aspect to compare">
                <input className={inputClass} value={aspect} maxLength={300} placeholder="e.g. data retention" onChange={(e) => setAspect(e.target.value)} />
              </Field>
              {picked.length < MIN_COMPARE && <p className="text-xs text-slate-500">Choose at least {MIN_COMPARE} documents to compare.</p>}
            </>
          )}
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={!canRun || active.isPending}>
              {tab === "summarize" ? "Summarize" : "Compare"}
            </Button>
            {active.isPending && <Spinner label="Reading, then checking every sentence against its source" />}
          </div>
          <ErrorBanner error={active.error} />
        </form>
      </Card>

      {result && (
        <Card title="Result">
          <AnswerView answer={result} onOpenSource={setSource} />
        </Card>
      )}
      <SourceViewer citation={source} onClose={() => setSource(null)} />
    </div>
  );
}
