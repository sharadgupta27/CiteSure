import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Schemas } from "../api/client";
import { useWorkspaces } from "../api/hooks";
import { useAuth } from "./AuthContext";

type Workspace = Schemas["Workspace"];

interface WorkspaceValue {
  workspaces: Workspace[];
  current: Workspace | undefined;
  isAdmin: boolean;
  loading: boolean;
  select: (id: string) => void;
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null);
const STORAGE_KEY = "citesure.workspace";

function readStored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const query = useWorkspaces(Boolean(user));
  const [selected, setSelected] = useState<string | null>(readStored);

  const workspaces = useMemo(() => query.data ?? [], [query.data]);
  const current = workspaces.find((w) => w.id === selected) ?? workspaces[0];

  useEffect(() => {
    if (!current) return;
    try {
      localStorage.setItem(STORAGE_KEY, current.id);
    } catch {
      /* ignore */
    }
  }, [current]);

  const value = useMemo<WorkspaceValue>(
    () => ({ workspaces, current, isAdmin: current?.role === "admin", loading: query.isLoading, select: setSelected }),
    [workspaces, current, query.isLoading],
  );
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  return value;
}
