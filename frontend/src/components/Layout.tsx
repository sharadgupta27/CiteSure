import { useState, type FormEvent } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useCreateWorkspace } from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { useWorkspace } from "../auth/WorkspaceContext";
import { Button, Card, ErrorBanner, Field, Spinner, inputClass } from "./ui";

const link = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100"}`;

export function Layout() {
  const { user, signOut } = useAuth();
  const { workspaces, current, isAdmin, loading, select } = useWorkspace();

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-2">
          <span className="mr-2 flex items-center gap-2 text-lg font-bold text-slate-900">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-indigo-600 text-white">✓</span>CiteSure
          </span>
          <nav className="flex flex-wrap gap-1" aria-label="Main">
            <NavLink to="/ask" className={link}>Ask</NavLink>
            <NavLink to="/documents" className={link}>Documents</NavLink>
            {isAdmin && (
              <>
                <NavLink to="/workspace" className={link}>Workspace</NavLink>
                <NavLink to="/feedback" className={link}>Feedback</NavLink>
                <NavLink to="/quality" className={link}>Quality</NavLink>
              </>
            )}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            {workspaces.length > 1 && (
              <select aria-label="Workspace" className={`${inputClass} w-auto`} value={current?.id} onChange={(e) => select(e.target.value)}>
                {workspaces.map((w) => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </select>
            )}
            {workspaces.length === 1 && <span className="text-slate-500">{current?.name}</span>}
            <span className="hidden text-slate-500 sm:inline">{user?.email}</span>
            <Button variant="secondary" onClick={signOut}>Sign out</Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        {loading ? <Spinner label="Loading your workspace…" /> : current ? <Outlet /> : <CreateFirstWorkspace />}
      </main>
    </div>
  );
}

function CreateFirstWorkspace() {
  const [name, setName] = useState("");
  const create = useCreateWorkspace();
  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) create.mutate(name.trim());
  }
  return (
    <div className="mx-auto max-w-md">
      <Card title="Create your workspace">
        <p className="mb-3 text-sm text-slate-600">
          You are not a member of any workspace yet. Create one (you become its admin), or ask an admin to add you.
        </p>
        <form onSubmit={submit} className="space-y-3">
          <Field label="Workspace name">
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Robotics" required />
          </Field>
          <ErrorBanner error={create.error} />
          <Button type="submit" disabled={create.isPending}>Create workspace</Button>
        </form>
      </Card>
    </div>
  );
}
