import { useState, type FormEvent } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useCreateWorkspace } from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { useWorkspace } from "../auth/WorkspaceContext";
import { Icon, Logo, type IconName } from "./Icon";
import { Button, Card, ErrorBanner, Field, Spinner, inputClass } from "./ui";

const COLLAPSED_KEY = "citesure.sidebar-collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function NavItem({ to, icon, label, collapsed, onNavigate }: { to: string; icon: IconName; label: string; collapsed: boolean; onNavigate: () => void }) {
  return (
    <NavLink
      to={to}
      aria-label={label}
      title={collapsed ? label : undefined}
      onClick={onNavigate}
      className={({ isActive }) =>
        `group flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors ${collapsed ? "lg:justify-center lg:px-0" : ""} ${
          isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
        }`
      }
    >
      <Icon name={icon} className="h-[18px] w-[18px]" />
      <span className={collapsed ? "lg:hidden" : ""}>{label}</span>
    </NavLink>
  );
}

export function Layout() {
  const { user, signOut } = useAuth();
  const { workspaces, current, isAdmin, loading, select } = useWorkspace();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [drawer, setDrawer] = useState(false);

  function toggleCollapsed() {
    setCollapsed((value) => {
      try {
        localStorage.setItem(COLLAPSED_KEY, value ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !value;
    });
  }

  const initial = (user?.email ?? "?").slice(0, 1).toUpperCase();
  const close = () => setDrawer(false);

  return (
    <div className="flex min-h-full bg-slate-50/60">
      {drawer && <div className="fixed inset-0 z-30 bg-slate-900/40 lg:hidden" onClick={close} aria-hidden="true" />}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-slate-200 bg-white transition-transform lg:sticky lg:top-0 lg:z-auto lg:h-screen lg:translate-x-0 ${
          collapsed ? "lg:w-[4.5rem]" : "lg:w-64"
        } ${drawer ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className={`flex items-center gap-2 px-4 pt-4 ${collapsed ? "lg:flex-col lg:px-0" : "justify-between"}`}>
          <Link to="/ask" className="flex items-center gap-2.5 text-lg font-bold tracking-tight text-slate-900" aria-label="CiteSure home">
            <Logo />
            <span className={collapsed ? "lg:hidden" : ""}>CiteSure</span>
          </Link>
          <button
            type="button"
            onClick={toggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="hidden rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800 lg:block"
          >
            <Icon name="panel" className="h-5 w-5" />
          </button>
          <button type="button" onClick={close} aria-label="Close menu" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 lg:hidden">
            <Icon name="close" className="h-5 w-5" />
          </button>
        </div>

        <div className={`mt-5 px-3 ${collapsed ? "lg:px-2" : ""}`}>
          <Link
            to="/ask"
            state={{ fresh: location.key }}
            onClick={close}
            title={collapsed ? "New thread" : undefined}
            className={`flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-800 shadow-sm transition-colors hover:border-indigo-300 hover:bg-indigo-50/50 ${collapsed ? "lg:justify-center lg:px-0" : ""}`}
          >
            <span className="grid h-5 w-5 place-items-center rounded-full bg-indigo-600 text-white">
              <Icon name="plus" className="h-3.5 w-3.5" />
            </span>
            <span className={collapsed ? "lg:hidden" : ""}>New thread</span>
          </Link>
        </div>

        <nav className={`mt-4 flex-1 space-y-1 overflow-y-auto px-3 ${collapsed ? "lg:px-2" : ""}`} aria-label="Main">
          <NavItem to="/ask" icon="ask" label="Ask" collapsed={collapsed} onNavigate={close} />
          <NavItem to="/documents" icon="documents" label="Documents" collapsed={collapsed} onNavigate={close} />
          {isAdmin && (
            <>
              <p className={`px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-slate-400 ${collapsed ? "lg:hidden" : ""}`}>Admin</p>
              <NavItem to="/workspace" icon="workspace" label="Workspace" collapsed={collapsed} onNavigate={close} />
              <NavItem to="/feedback" icon="feedback" label="Feedback" collapsed={collapsed} onNavigate={close} />
              <NavItem to="/quality" icon="quality" label="Quality" collapsed={collapsed} onNavigate={close} />
            </>
          )}
        </nav>

        <div className={`space-y-3 border-t border-slate-100 p-3 ${collapsed ? "lg:p-2" : ""}`}>
          {workspaces.length > 1 && (
            <select
              aria-label="Workspace"
              className={`${inputClass} ${collapsed ? "lg:hidden" : ""}`}
              value={current?.id}
              onChange={(e) => select(e.target.value)}
            >
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          )}
          <div className={`flex items-center gap-2.5 rounded-xl bg-slate-50 p-2 ${collapsed ? "lg:flex-col lg:bg-transparent" : ""}`}>
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-amber-300 to-orange-400 text-sm font-bold text-slate-900">
              {initial}
            </span>
            <div className={`min-w-0 flex-1 ${collapsed ? "lg:hidden" : ""}`}>
              <p className="truncate text-sm font-medium text-slate-900">{user?.email}</p>
              <p className="truncate text-xs text-slate-500">
                {current?.name}
                {current && ` · ${current.role}`}
              </p>
            </div>
            <button
              type="button"
              onClick={signOut}
              aria-label="Sign out"
              title="Sign out"
              className="rounded-lg p-1.5 text-slate-500 hover:bg-white hover:text-slate-900"
            >
              <Icon name="logout" className="h-[18px] w-[18px]" />
            </button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-200 bg-white/90 px-4 py-2.5 backdrop-blur lg:hidden">
          <button type="button" onClick={() => setDrawer(true)} aria-label="Open menu" className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-100">
            <Icon name="menu" className="h-5 w-5" />
          </button>
          <span className="flex items-center gap-2 font-bold text-slate-900">
            <Logo className="h-6 w-6" />
            CiteSure
          </span>
        </header>
        <main className="w-full flex-1 px-4 py-6 sm:px-8 sm:py-8">
          {loading ? <Spinner label="Loading your workspace…" /> : current ? <div className={location.pathname === "/ask" ? "" : "mx-auto max-w-6xl"}><Outlet key={location.key} /></div> : <CreateFirstWorkspace />}
        </main>
      </div>
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
