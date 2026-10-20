/**
 * The ONLY place that talks HTTP (besides stream.ts for Server-Sent Events). Every request is typed from
 * openapi.yaml through the generated `schema.d.ts`, so a contract change that breaks the UI fails `npm run typecheck`.
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Answer = Schemas["Answer"];
export type Claim = Schemas["Claim"];
export type Citation = Schemas["Citation"];

export const API_BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let token: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setAuthToken(value: string | null): void {
  token = value;
}
export function getAuthToken(): string | null {
  return token;
}
/** Called when the server rejects the token (expired or revoked), so the app can send the user to the login page. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

const authMiddleware: Middleware = {
  onRequest({ request }) {
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response, request }) {
    // A failed login is also a 401 but must show its own error message instead of redirecting.
    if (response.status === 401 && !request.url.includes("/auth/")) onUnauthorized?.();
    return undefined;
  },
};

// openapi-fetch builds `new Request(url)`, which needs an absolute URL outside a real browser (tests, SSR).
const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost";
// `fetch` is looked up on every call (not captured once), so tests can stub it and polyfills still apply.
export const api = createClient<paths>({ baseUrl: `${origin}${API_BASE}`, fetch: (request) => globalThis.fetch(request) });
api.use(authMiddleware);

/** Turn an openapi-fetch result into its data, or throw an ApiError with the server's message. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    const body = (result.error ?? {}) as { code?: string; detail?: string };
    throw new ApiError(result.response.status, body.code ?? "error", body.detail ?? `Request failed (${result.response.status})`);
  }
  return result.data;
}

/** Download a file through the authenticated client and return it as a Blob (used for "open original"). */
export async function downloadDocument(documentId: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/file`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new ApiError(response.status, "download_failed", "Could not download the file");
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "document";
  return { blob: await response.blob(), filename };
}
