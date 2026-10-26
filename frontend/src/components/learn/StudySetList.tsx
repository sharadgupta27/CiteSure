import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useCreateStudySet, useStudySets } from "../../api/hooksLearning";
import { Button, Card, Empty, ErrorBanner, Field, Spinner, inputClass } from "../ui";
import { ProgressBar } from "./ProgressBar";

/** The user's study sets in a workspace, with a form to start a new one. */
export function StudySetList({ workspaceId }: { workspaceId: string }) {
  const sets = useStudySets(workspaceId);
  const create = useCreateStudySet(workspaceId);
  const [name, setName] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    create.mutate({ name: name.trim() }, { onSuccess: () => setName("") });
  }

  return (
    <div className="space-y-4">
      <Card title="New study set">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <div className="min-w-56 flex-1">
            <Field label="Name">
              <input className={inputClass} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="e.g. Onboarding reading" />
            </Field>
          </div>
          <Button type="submit" disabled={create.isPending || !name.trim()}>
            Create
          </Button>
        </form>
        <div className="mt-2">
          <ErrorBanner error={create.error} />
        </div>
      </Card>
      {sets.isLoading && <Spinner label="Loading study sets" />}
      <ErrorBanner error={sets.error} />
      {sets.data && sets.data.length === 0 && <Empty>No study sets yet. A study set is your own reading list; it never changes who can read what.</Empty>}
      <ul className="grid gap-3 sm:grid-cols-2">
        {sets.data?.map((set) => (
          <li key={set.id}>
            <Link
              to={`/learn/sets/${set.id}`}
              className="block rounded-2xl border border-slate-200/80 bg-white p-4 shadow-soft transition-colors hover:border-indigo-300"
            >
              <p className="font-semibold text-slate-900">{set.name}</p>
              {set.description && <p className="mt-0.5 text-sm text-slate-500">{set.description}</p>}
              <p className="mt-2 text-xs text-slate-500">
                {set.item_count} item{set.item_count === 1 ? "" : "s"} - {set.progress.documents_finished} of {set.progress.documents_total} documents finished
              </p>
              <ProgressBar className="mt-1.5" percent={set.progress.percent} label={`Progress in ${set.name}`} />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
