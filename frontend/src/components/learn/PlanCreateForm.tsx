import { useState, type FormEvent } from "react";
import { useCreateLearningPlan, useStudySets } from "../../api/hooksLearning";
import { Button, Card, ErrorBanner, Field, Spinner, inputClass } from "../ui";
import { DocumentPicker, type PickedDocument } from "./DocumentPicker";

const MAX_DOCUMENTS = 12;
type Mode = "set" | "topic";

/** Start a learning plan from a study set, or from a topic and a handful of documents. */
export function PlanCreateForm({ workspaceId, onCreated }: { workspaceId: string; onCreated: (planId: string) => void }) {
  const sets = useStudySets(workspaceId);
  const create = useCreateLearningPlan(workspaceId);
  const [mode, setMode] = useState<Mode>("set");
  const [setId, setSetId] = useState("");
  const [topic, setTopic] = useState("");
  const [title, setTitle] = useState("");
  const [hours, setHours] = useState("4");
  const [picked, setPicked] = useState<PickedDocument[]>([]);

  const chosenSet = setId || sets.data?.[0]?.id || "";
  const hoursValue = Number(hours);
  const valid =
    hoursValue > 0 && hoursValue <= 80 && (mode === "set" ? Boolean(chosenSet) : topic.trim().length >= 3 && picked.length > 0);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    create.mutate(
      {
        title: title.trim() || null,
        hours_per_week: hoursValue,
        ...(mode === "set" ? { study_set_id: chosenSet } : { topic: topic.trim(), document_ids: picked.map((d) => d.id) }),
      },
      { onSuccess: (plan) => onCreated(plan.id) },
    );
  }

  return (
    <Card title="New learning plan">
      <form onSubmit={submit} className="space-y-4">
        <fieldset className="flex gap-4 text-sm">
          <legend className="sr-only">Plan source</legend>
          <label className="flex items-center gap-1.5">
            <input type="radio" name="plan-mode" checked={mode === "set"} onChange={() => setMode("set")} /> From a study set
          </label>
          <label className="flex items-center gap-1.5">
            <input type="radio" name="plan-mode" checked={mode === "topic"} onChange={() => setMode("topic")} /> From a topic
          </label>
        </fieldset>

        {mode === "set" ? (
          sets.data && sets.data.length === 0 ? (
            <p className="text-sm text-slate-500">Create a study set first, or switch to a topic.</p>
          ) : (
            <Field label="Study set">
              <select className={inputClass} value={chosenSet} onChange={(e) => setSetId(e.target.value)}>
                {sets.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
          )
        ) : (
          <>
            <Field label="Topic">
              <input className={inputClass} value={topic} maxLength={300} placeholder="e.g. data retention" onChange={(e) => setTopic(e.target.value)} />
            </Field>
            <DocumentPicker workspaceId={workspaceId} legend={`Documents to read (up to ${MAX_DOCUMENTS})`} selected={picked} onChange={setPicked} max={MAX_DOCUMENTS} />
          </>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Plan title (optional)">
            <input className={inputClass} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="Hours per week">
            <input className={inputClass} type="number" min={0.5} max={80} step={0.5} value={hours} onChange={(e) => setHours(e.target.value)} />
          </Field>
        </div>

        <p className="text-xs text-slate-500">
          Steps, order and time estimates come from the documents' structure. Each step's objective is generated, then every sentence is checked against its source;
          anything unsupported is dropped.
        </p>
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={!valid || create.isPending}>
            Create plan
          </Button>
          {create.isPending && <Spinner label="Building and verifying the plan" />}
        </div>
        <ErrorBanner error={create.error} />
      </form>
    </Card>
  );
}
