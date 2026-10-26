/** TanStack Query hooks for open-access full text (phase 3). Pages and components never call `api` directly. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useWorkspace } from "../auth/WorkspaceContext";
import { api, unwrap, type Schemas } from "./client";

export type FullTextStatus = Schemas["FullTextStatus"];

export const fulltextKeys = {
  status: (id: string) => ["fulltext", id] as const,
};

const POLL_MS = 1500;
const WORKING = new Set<FullTextStatus["status"]>(["queued", "running"]);

/** Ask the server to add a paper's open-access full text. The download runs in the worker; poll `useFullTextStatus`. */
export function useRequestFullText() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schemas["FullTextFetchRequest"]) => unwrap(await api.POST("/research/fulltext", { body })),
    onSuccess: (data) => qc.setQueryData(fulltextKeys.status(data.id), data),
  });
}

/** Progress of one request; polls until it is ready or has failed. */
export function useFullTextStatus(id: string | undefined) {
  return useQuery({
    queryKey: fulltextKeys.status(id ?? ""),
    queryFn: async () => unwrap(await api.GET("/research/fulltext/{request_id}", { params: { path: { request_id: id! } } })),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data && WORKING.has(query.state.data.status) ? POLL_MS : false),
  });
}

/** The selected workspace's id, or undefined when rendered outside a workspace provider (a preview, a test). */
export function useActiveWorkspaceId(): string | undefined {
  try {
    // useContext runs on every render; it is only the missing provider that throws, so the hook order never changes
    return useWorkspace().current?.id;
  } catch {
    return undefined;
  }
}
