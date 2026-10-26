/** Hooks for the admin-only pages added in phase 5 (audit log, dashboard) and the login page's sign-in options. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { API_BASE, ApiError, api, getAuthToken, unwrap, type Schemas } from "./client";

export type AuditEvent = Schemas["AuditEvent"];
export type AuditEventPage = Schemas["AuditEventPage"];
export type AuditChainStatus = Schemas["AuditChainStatus"];
export type Dashboard = Schemas["Dashboard"];
export type AuthConfig = Schemas["AuthConfig"];

export interface AuditFilters {
  actor?: string;
  action?: string;
  /** ISO date-time (inclusive) */
  since?: string;
  /** ISO date-time (exclusive) */
  until?: string;
}

export const AUDIT_PAGE_SIZE = 25;

export const adminKeys = {
  authConfig: ["auth-config"] as const,
  audit: (ws: string, filters: AuditFilters, offset: number) => ["audit", ws, filters, offset] as const,
  dashboard: (ws: string, days: number) => ["dashboard", ws, days] as const,
};

/** What the login page offers. A failure (old server, offline) falls back to the plain password form. */
export function useAuthConfig() {
  return useQuery({
    queryKey: adminKeys.authConfig,
    queryFn: async () => unwrap(await api.GET("/auth/config")),
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useAuditEvents(ws: string | undefined, filters: AuditFilters, offset: number) {
  return useQuery({
    queryKey: adminKeys.audit(ws ?? "", filters, offset),
    queryFn: async () =>
      unwrap(
        await api.GET("/workspaces/{workspace_id}/audit-events", {
          params: { path: { workspace_id: ws! }, query: { ...filters, limit: AUDIT_PAGE_SIZE, offset } },
        }),
      ),
    enabled: Boolean(ws),
    placeholderData: (previous) => previous,
  });
}

export function useVerifyAuditChain(ws: string | undefined) {
  return useMutation({
    mutationFn: async () =>
      unwrap(await api.GET("/workspaces/{workspace_id}/audit-events/verify", { params: { path: { workspace_id: ws! } } })),
  });
}

/** The CSV goes through the authenticated fetch (a plain link would carry no token) and is saved by the page. */
export async function downloadAuditCsv(ws: string, filters: AuditFilters): Promise<Blob> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) query.set(key, value);
  const token = getAuthToken();
  const response = await fetch(`${API_BASE}/workspaces/${ws}/audit-events/export?${query.toString()}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new ApiError(response.status, "export_failed", "Could not export the audit log");
  return response.blob();
}

export function useDashboard(ws: string | undefined, days: number) {
  return useQuery({
    queryKey: adminKeys.dashboard(ws ?? "", days),
    queryFn: async () =>
      unwrap(
        await api.GET("/workspaces/{workspace_id}/dashboard", { params: { path: { workspace_id: ws! }, query: { days } } }),
      ),
    enabled: Boolean(ws),
  });
}
