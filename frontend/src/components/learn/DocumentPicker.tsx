import { useState } from "react";
import { useCollections, useDocuments } from "../../api/hooks";
import { Empty, Field, Spinner, inputClass } from "../ui";

export interface PickedDocument {
  id: string;
  title: string;
}

interface Props {
  workspaceId: string;
  selected: PickedDocument[];
  onChange: (next: PickedDocument[]) => void;
  /** At most this many documents can be selected (others are disabled). */
  max?: number;
  /** Documents that cannot be chosen again, e.g. already in the study set. */
  excludeIds?: string[];
  legend: string;
}

/** Choose workspace documents, collection by collection. The server lists only what the user may read. */
export function DocumentPicker({ workspaceId, selected, onChange, max, excludeIds = [], legend }: Props) {
  const collections = useCollections(workspaceId);
  const [chosen, setChosen] = useState<string>("");
  const collectionId = chosen || collections.data?.[0]?.id;
  const documents = useDocuments(collectionId);
  const ready = (documents.data ?? []).filter((d) => d.status === "ready" && !excludeIds.includes(d.id));
  const isSelected = (id: string) => selected.some((d) => d.id === id);
  const full = max !== undefined && selected.length >= max;

  function toggle(id: string, title: string) {
    onChange(isSelected(id) ? selected.filter((d) => d.id !== id) : [...selected, { id, title }]);
  }

  if (collections.isLoading) return <Spinner label="Loading collections" />;
  if (!collections.data?.length) return <Empty>There are no collections you can read in this workspace yet.</Empty>;

  return (
    <fieldset className="space-y-2">
      <legend className="mb-1 text-sm font-medium text-slate-700">{legend}</legend>
      <Field label="Collection">
        <select className={inputClass} value={collectionId ?? ""} onChange={(e) => setChosen(e.target.value)}>
          {collections.data.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </Field>
      {documents.isLoading ? (
        <Spinner label="Loading documents" />
      ) : ready.length === 0 ? (
        <p className="text-sm text-slate-500">No documents ready to choose in this collection.</p>
      ) : (
        <ul className="max-h-48 space-y-1 overflow-y-auto rounded-xl border border-slate-200 p-2">
          {ready.map((d) => (
            <li key={d.id}>
              <label className="flex items-center gap-2 text-sm text-slate-800">
                <input
                  type="checkbox"
                  checked={isSelected(d.id)}
                  disabled={!isSelected(d.id) && full}
                  onChange={() => toggle(d.id, d.title)}
                />
                {d.title}
              </label>
            </li>
          ))}
        </ul>
      )}
      {selected.length > 0 && (
        <p className="text-xs text-slate-500">
          Selected ({selected.length}
          {max ? ` of ${max}` : ""}): {selected.map((d) => d.title).join(", ")}
        </p>
      )}
    </fieldset>
  );
}
