import { useState, type FormEvent } from "react";
import { useAddGroupMember, useAddMember, useCollections, useCreateCollection, useCreateGroup, useDeleteCollection, useGroups, useMembers } from "../api/hooks";
import { useWorkspace } from "../auth/WorkspaceContext";
import { Badge, Button, Card, Empty, ErrorBanner, Field, inputClass } from "../components/ui";

export function WorkspacePage() {
  const { current } = useWorkspace();
  if (!current) return null;
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-slate-900">Workspace: {current.name}</h1>
      <p className="max-w-3xl text-sm text-slate-600">
        Access control lives here. A collection is either open to every member, or restricted to groups. People who are not allowed to read a
        collection never see its documents, and the assistant never retrieves them for those people.
      </p>
      <div className="grid gap-6 lg:grid-cols-2">
        <Collections workspaceId={current.id} />
        <div className="space-y-6">
          <Groups workspaceId={current.id} />
          <Members workspaceId={current.id} />
        </div>
      </div>
    </div>
  );
}

function Collections({ workspaceId }: { workspaceId: string }) {
  const collections = useCollections(workspaceId);
  const groups = useGroups(workspaceId);
  const create = useCreateCollection(workspaceId);
  const remove = useDeleteCollection(workspaceId);
  const [name, setName] = useState("");
  const [restricted, setRestricted] = useState(false);
  const [groupIds, setGroupIds] = useState<string[]>([]);

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(
      { name: name.trim(), visibility: restricted ? "groups" : "workspace", group_ids: restricted ? groupIds : [] },
      {
        onSuccess: () => {
          setName("");
          setRestricted(false);
          setGroupIds([]);
        },
      },
    );
  }

  const groupName = (id: string) => groups.data?.find((g) => g.id === id)?.name ?? "group";

  return (
    <Card title="Collections">
      <ul className="mb-4 divide-y divide-slate-100">
        {collections.data?.map((c) => (
          <li key={c.id} className="flex items-center justify-between gap-2 py-2">
            <div>
              <span className="font-medium text-slate-900">{c.name}</span>{" "}
              <Badge value={c.visibility} />
              {c.visibility === "groups" && <span className="ml-2 text-xs text-slate-500">readable by: {c.group_ids.map(groupName).join(", ")}</span>}
            </div>
            <Button
              variant="danger"
              onClick={() => {
                if (window.confirm(`Delete "${c.name}" with all its documents?`)) remove.mutate(c.id);
              }}
            >
              Delete
            </Button>
          </li>
        ))}
      </ul>
      {collections.data?.length === 0 && <Empty>No collections yet.</Empty>}
      <form onSubmit={submit} className="space-y-3 border-t border-slate-100 pt-3">
        <Field label="New collection name">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required placeholder="People-Ops-Confidential" />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={restricted} onChange={(e) => setRestricted(e.target.checked)} />
          Restrict to specific groups
        </label>
        {restricted && (
          <fieldset className="space-y-1 text-sm">
            <legend className="mb-1 font-medium text-slate-700">Who can read it</legend>
            {groups.data?.length === 0 && <p className="text-slate-500">Create a group first.</p>}
            {groups.data?.map((g) => (
              <label key={g.id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={groupIds.includes(g.id)}
                  onChange={(e) => setGroupIds((ids) => (e.target.checked ? [...ids, g.id] : ids.filter((id) => id !== g.id)))}
                />
                {g.name}
              </label>
            ))}
          </fieldset>
        )}
        <ErrorBanner error={create.error ?? remove.error} />
        <Button type="submit" disabled={create.isPending || (restricted && groupIds.length === 0)}>
          Create collection
        </Button>
      </form>
    </Card>
  );
}

function Groups({ workspaceId }: { workspaceId: string }) {
  const groups = useGroups(workspaceId);
  const members = useMembers(workspaceId);
  const create = useCreateGroup(workspaceId);
  const addMember = useAddGroupMember(workspaceId);
  const [name, setName] = useState("");
  const [emails, setEmails] = useState<Record<string, string>>({});
  const emailOf = (id: string) => members.data?.find((m) => m.user_id === id)?.email ?? id;

  return (
    <Card title="Groups">
      <ul className="mb-3 space-y-3">
        {groups.data?.map((g) => (
          <li key={g.id} className="text-sm">
            <div className="font-medium text-slate-900">{g.name}</div>
            <div className="text-xs text-slate-500">{g.member_ids.length > 0 ? g.member_ids.map(emailOf).join(", ") : "No members yet"}</div>
            <form
              className="mt-1 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                addMember.mutate({ groupId: g.id, email: emails[g.id] ?? "" }, { onSuccess: () => setEmails((v) => ({ ...v, [g.id]: "" })) });
              }}
            >
              <input
                className={inputClass}
                type="email"
                placeholder="member email"
                aria-label={`Add member to ${g.name}`}
                value={emails[g.id] ?? ""}
                onChange={(e) => setEmails((v) => ({ ...v, [g.id]: e.target.value }))}
                required
              />
              <Button type="submit" variant="secondary">
                Add
              </Button>
            </form>
          </li>
        ))}
      </ul>
      <form
        className="flex gap-2 border-t border-slate-100 pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(name.trim(), { onSuccess: () => setName("") });
        }}
      >
        <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="New group (for example hr)" aria-label="New group name" required />
        <Button type="submit">Create</Button>
      </form>
      <ErrorBanner error={create.error ?? addMember.error} />
    </Card>
  );
}

function Members({ workspaceId }: { workspaceId: string }) {
  const members = useMembers(workspaceId);
  const add = useAddMember(workspaceId);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"member" | "admin">("member");

  return (
    <Card title="Members">
      <ul className="mb-3 divide-y divide-slate-100 text-sm">
        {members.data?.map((m) => (
          <li key={m.user_id} className="flex items-center justify-between py-1.5">
            {m.email}
            <Badge value={m.role} />
          </li>
        ))}
      </ul>
      <form
        className="flex flex-wrap gap-2 border-t border-slate-100 pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate({ email, role }, { onSuccess: () => setEmail("") });
        }}
      >
        <input className={`${inputClass} flex-1`} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="person@company.com" aria-label="Member email" required />
        <select className={`${inputClass} w-auto`} value={role} onChange={(e) => setRole(e.target.value as "member" | "admin")} aria-label="Role">
          <option value="member">member</option>
          <option value="admin">admin</option>
        </select>
        <Button type="submit">Add member</Button>
      </form>
      <p className="mt-1 text-xs text-slate-500">The person must have registered first.</p>
      <ErrorBanner error={add.error} />
    </Card>
  );
}
