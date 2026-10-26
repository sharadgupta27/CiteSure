import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  useAddStudySetItem,
  useDeleteStudySet,
  useRemoveStudySetItem,
  useStudySet,
  useUpdateStudySet,
  useUpdateStudySetItem,
  type StudySetItem,
} from "../../api/hooksLearning";
import { Button, Card, Empty, ErrorBanner, Field, Spinner, inputClass } from "../ui";
import { DocumentPicker, type PickedDocument } from "./DocumentPicker";
import { ProgressBar } from "./ProgressBar";

function ItemRow({ setId, item }: { setId: string; item: StudySetItem }) {
  const update = useUpdateStudySetItem(setId);
  const remove = useRemoveStudySetItem(setId);
  const [note, setNote] = useState(item.note);
  useEffect(() => setNote(item.note), [item.note]);

  return (
    <li className="space-y-2 rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium text-slate-900">
            {item.kind === "reference" && item.url ? (
              <a href={item.url} target="_blank" rel="noreferrer noopener" className="underline decoration-dotted hover:text-indigo-700">
                {item.title}
              </a>
            ) : (
              item.title
            )}
          </p>
          <p className="text-xs text-slate-500">
            {item.kind === "reference" ? `Saved public paper${item.source ? ` (${item.source})` : ""}` : item.page_count ? `${item.page_count} pages` : "Document"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {item.kind === "reference" && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">Public</span>}
          <Button variant="danger" className="!px-2 !py-1 text-xs" aria-label={`Remove ${item.title}`} disabled={remove.isPending} onClick={() => remove.mutate(item.id)}>
            Remove
          </Button>
        </div>
      </div>
      {item.percent !== null && <ProgressBar percent={item.percent} label={`Reading progress in ${item.title}`} />}
      <div className="flex items-center gap-2">
        <input
          className={inputClass}
          aria-label={`Note for ${item.title}`}
          placeholder="Add a note"
          maxLength={2000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        {note !== item.note && (
          <Button variant="secondary" className="shrink-0" disabled={update.isPending} onClick={() => update.mutate({ itemId: item.id, body: { note } })}>
            Save note
          </Button>
        )}
      </div>
    </li>
  );
}

function AddReference({ setId }: { setId: string }) {
  const add = useAddStudySetItem(setId);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate(
      { reference: { title: title.trim(), url: url.trim() } },
      {
        onSuccess: () => {
          setTitle("");
          setUrl("");
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <Field label="Paper title">
        <input className={inputClass} value={title} maxLength={300} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <Field label="Paper link">
        <input className={inputClass} value={url} type="url" placeholder="https://" maxLength={1000} onChange={(e) => setUrl(e.target.value)} />
      </Field>
      <p className="text-xs text-slate-500">Only the title and link are saved. Nothing is downloaded, so a saved paper cannot be summarized or planned.</p>
      <Button type="submit" variant="secondary" disabled={add.isPending || !title.trim() || !url.trim()}>
        Save paper
      </Button>
      <ErrorBanner error={add.error} />
    </form>
  );
}

/** One study set: its items with progress, a document picker, saved public papers, notes, rename and delete. */
export function StudySetDetail({ setId }: { setId: string }) {
  const set = useStudySet(setId);
  const update = useUpdateStudySet(setId);
  const add = useAddStudySetItem(setId);
  const remove = useDeleteStudySet(set.data?.workspace_id ?? "");
  const navigate = useNavigate();
  const [picked, setPicked] = useState<PickedDocument[]>([]);
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [renaming, setRenaming] = useState(false);

  useEffect(() => {
    if (set.data) {
      setName(set.data.name);
      setNotes(set.data.notes);
    }
  }, [set.data]);

  if (set.isLoading) return <Spinner label="Loading study set" />;
  if (set.error || !set.data) return <ErrorBanner error={set.error ?? new Error("Study set not found")} />;
  const data = set.data;

  async function addPicked() {
    for (const doc of picked) await add.mutateAsync({ document_id: doc.id }).catch(() => undefined);
    setPicked([]);
  }

  return (
    <div className="space-y-4">
      <Link to="/learn/sets" className="text-sm text-indigo-700 hover:underline">
        All study sets
      </Link>
      <Card
        title={data.name}
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setRenaming((v) => !v)}>
              Rename
            </Button>
            <Button
              variant="danger"
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(`Delete the study set "${data.name}"? Its documents are not deleted.`)) {
                  remove.mutate(data.id, { onSuccess: () => navigate("/learn/sets") });
                }
              }}
            >
              Delete
            </Button>
          </div>
        }
      >
        {renaming && (
          <form
            className="mb-3 flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              update.mutate({ name: name.trim() }, { onSuccess: () => setRenaming(false) });
            }}
          >
            <div className="flex-1">
              <Field label="Study set name">
                <input className={inputClass} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
              </Field>
            </div>
            <Button type="submit" disabled={update.isPending || !name.trim()}>
              Save name
            </Button>
          </form>
        )}
        <p className="mb-1 text-sm text-slate-600">
          {data.progress.documents_finished} of {data.progress.documents_total} documents finished, {Math.round(data.progress.percent)}% overall
        </p>
        <ProgressBar percent={data.progress.percent} label="Study set progress" />
        <div className="mt-2 space-y-2">
          <ErrorBanner error={update.error} />
          <ErrorBanner error={remove.error} />
        </div>
      </Card>

      <Card title="Items">
        {data.items.length === 0 ? (
          <Empty>This study set is empty. Add documents below.</Empty>
        ) : (
          <ul className="space-y-2">
            {data.items.map((item) => (
              <ItemRow key={item.id} setId={data.id} item={item} />
            ))}
          </ul>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Add documents">
          <DocumentPicker
            workspaceId={data.workspace_id}
            legend="Documents you can read"
            selected={picked}
            onChange={setPicked}
            excludeIds={data.items.flatMap((i) => (i.document_id ? [i.document_id] : []))}
          />
          <div className="mt-3 space-y-2">
            <Button disabled={picked.length === 0 || add.isPending} onClick={() => void addPicked()}>
              Add selected
            </Button>
            <ErrorBanner error={add.error} />
          </div>
        </Card>
        <Card title="Save a public paper">
          <AddReference setId={data.id} />
        </Card>
      </div>

      <Card title="Notes">
        <Field label="Study set notes">
          <textarea className={inputClass} rows={5} maxLength={20000} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <div className="mt-2">
          <Button variant="secondary" disabled={update.isPending || notes === data.notes} onClick={() => update.mutate({ notes })}>
            Save notes
          </Button>
        </div>
      </Card>
    </div>
  );
}
