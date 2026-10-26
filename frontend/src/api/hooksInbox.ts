/** Hooks for the watched-folder inbox page (workspace admins only). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "./client";

export type InboxStatus = Schemas["InboxStatus"];
export type InboxFolder = Schemas["InboxFolder"];
export type InboxItem = Schemas["InboxItem"];
export type InboxItemStatus = Schemas["InboxItemStatus"];

export const inboxKeys = {
  status: (ws: string) => ["inbox", ws, "status"] as const,
  items: (ws: string, status: InboxItemStatus | undefined) => ["inbox", ws, "items", status ?? "all"] as const,
  all: (ws: string) => ["inbox", ws] as const,
};

/** The worker scans in the background, so the page re-reads every few seconds while it is open. */
const REFRESH_MS = 5000;

export function useInboxStatus(ws: string | undefined) {
  return useQuery({
    queryKey: inboxKeys.status(ws ?? ""),
    queryFn: async () => unwrap(await api.GET("/workspaces/{workspace_id}/inbox", { params: { path: { workspace_id: ws! } } })),
    enabled: Boolean(ws),
    refetchInterval: REFRESH_MS,
  });
}

export function useInboxItems(ws: string | undefined, status: InboxItemStatus | undefined) {
  return useQuery({
    queryKey: inboxKeys.items(ws ?? "", status),
    queryFn: async () =>
      unwrap(
        await api.GET("/workspaces/{workspace_id}/inbox/items", {
          params: { path: { workspace_id: ws! }, query: { status, limit: 100 } },
        }),
      ),
    enabled: Boolean(ws),
    refetchInterval: REFRESH_MS,
  });
}

export function useRequestInboxScan(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await api.POST("/workspaces/{workspace_id}/inbox/scan", { params: { path: { workspace_id: ws } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: inboxKeys.all(ws) }),
  });
}
