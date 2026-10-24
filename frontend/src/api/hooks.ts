/** TanStack Query hooks around the typed client. Pages never call `api` directly. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "./client";

export const keys = {
  workspaces: ["workspaces"] as const,
  members: (ws: string) => ["members", ws] as const,
  groups: (ws: string) => ["groups", ws] as const,
  collections: (ws: string) => ["collections", ws] as const,
  documents: (collection: string) => ["documents", collection] as const,
  chunks: (document: string) => ["chunks", document] as const,
  chunk: (chunk: string) => ["chunk", chunk] as const,
  threads: (ws: string) => ["threads", ws] as const,
  thread: (id: string) => ["thread", id] as const,
  publicResearch: ["public-research"] as const,
  feedback: (ws: string) => ["feedback", ws] as const,
  golden: (ws: string) => ["golden", ws] as const,
  runs: (ws: string) => ["runs", ws] as const,
  run: (id: string) => ["run", id] as const,
  compare: (base: string, head: string) => ["compare", base, head] as const,
};

const idle = (id: string | undefined) => ({ enabled: Boolean(id) });

// --- auth ---------------------------------------------------------------------------------
export const login = async (email: string, password: string) =>
  unwrap(await api.POST("/auth/login", { body: { email, password } }));
export const register = async (email: string, password: string) =>
  unwrap(await api.POST("/auth/register", { body: { email, password } }));
export const fetchMe = async () => unwrap(await api.GET("/auth/me"));

// --- workspaces ---------------------------------------------------------------------------
export function useWorkspaces(enabled = true) {
  return useQuery({ queryKey: keys.workspaces, queryFn: async () => unwrap(await api.GET("/workspaces")), enabled });
}
export function useCreateWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => unwrap(await api.POST("/workspaces", { body: { name } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.workspaces }),
  });
}
export function useMembers(ws: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.members(ws ?? ""),
    queryFn: async () => unwrap(await api.GET("/workspaces/{workspace_id}/members", { params: { path: { workspace_id: ws! } } })),
    enabled: Boolean(ws) && enabled,
  });
}
export function useAddMember(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schemas["MemberAdd"]) =>
      unwrap(await api.POST("/workspaces/{workspace_id}/members", { params: { path: { workspace_id: ws } }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.members(ws) }),
  });
}
export function useGroups(ws: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.groups(ws ?? ""),
    queryFn: async () => unwrap(await api.GET("/workspaces/{workspace_id}/groups", { params: { path: { workspace_id: ws! } } })),
    enabled: Boolean(ws) && enabled,
  });
}
export function useCreateGroup(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) =>
      unwrap(await api.POST("/workspaces/{workspace_id}/groups", { params: { path: { workspace_id: ws } }, body: { name } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.groups(ws) }),
  });
}
export function useAddGroupMember(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { groupId: string; email: string }) =>
      unwrap(await api.POST("/groups/{group_id}/members", { params: { path: { group_id: vars.groupId } }, body: { email: vars.email } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.groups(ws) }),
  });
}

// --- collections and documents ------------------------------------------------------------
export function useCollections(ws: string | undefined) {
  return useQuery({
    queryKey: keys.collections(ws ?? ""),
    queryFn: async () => unwrap(await api.GET("/workspaces/{workspace_id}/collections", { params: { path: { workspace_id: ws! } } })),
    ...idle(ws),
  });
}
export function useCreateCollection(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schemas["CollectionCreate"]) =>
      unwrap(await api.POST("/workspaces/{workspace_id}/collections", { params: { path: { workspace_id: ws } }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.collections(ws) }),
  });
}
export function useDeleteCollection(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const result = await api.DELETE("/collections/{collection_id}", { params: { path: { collection_id: id } } });
      if (result.error) unwrap(result as never);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.collections(ws) }),
  });
}

const PENDING = new Set(["queued", "parsing", "embedding"]);
export function useDocuments(collection: string | undefined) {
  return useQuery({
    queryKey: keys.documents(collection ?? ""),
    queryFn: async () => unwrap(await api.GET("/collections/{collection_id}/documents", { params: { path: { collection_id: collection! } } })),
    ...idle(collection),
    // Ingestion runs in the background: keep polling until every document is ready or failed.
    refetchInterval: (query) => (query.state.data?.some((d) => PENDING.has(d.status)) ? 1500 : false),
  });
}
export function useUploadDocument(collection: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return unwrap(
        await api.POST("/collections/{collection_id}/documents", {
          params: { path: { collection_id: collection } },
          body: { file: "" },
          bodySerializer: () => form,
        }),
      );
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.documents(collection) }),
  });
}
export function useDeleteDocument(collection: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const result = await api.DELETE("/documents/{document_id}", { params: { path: { document_id: id } } });
      if (result.error) unwrap(result as never);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.documents(collection) }),
  });
}
export function useReindexDocument(collection: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => unwrap(await api.POST("/documents/{document_id}/reindex", { params: { path: { document_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.documents(collection) }),
  });
}
export function useDocumentChunks(documentId: string | undefined) {
  return useQuery({
    queryKey: keys.chunks(documentId ?? ""),
    queryFn: async () => unwrap(await api.GET("/documents/{document_id}/chunks", { params: { path: { document_id: documentId! } } })),
    ...idle(documentId),
  });
}

// --- ask ----------------------------------------------------------------------------------
export function useThreads(ws: string | undefined) {
  return useQuery({
    queryKey: keys.threads(ws ?? ""),
    queryFn: async () => unwrap(await api.GET("/threads", { params: { query: { workspace_id: ws! } } })),
    ...idle(ws),
  });
}
/** Whether the public research lane is on, and whether the server runs in private mode. */
export function usePublicResearchStatus() {
  return useQuery({
    queryKey: keys.publicResearch,
    queryFn: async () => unwrap(await api.GET("/public-research")),
    staleTime: 5 * 60 * 1000,
  });
}
/** Shows the exact query that would leave the system, and the egress guard's verdict. Sends nothing. */
export function usePreviewPublicQuery() {
  return useMutation({
    mutationFn: async (body: Schemas["PublicQueryPreviewRequest"]) => unwrap(await api.POST("/public-research/preview", { body })),
  });
}
export function useThread(id: string | undefined) {
  return useQuery({
    queryKey: keys.thread(id ?? ""),
    queryFn: async () => unwrap(await api.GET("/threads/{thread_id}", { params: { path: { thread_id: id! } } })),
    ...idle(id),
  });
}
export function useSendFeedback() {
  return useMutation({
    mutationFn: async (vars: { answerId: string; rating: -1 | 1; comment: string | null }) =>
      unwrap(await api.POST("/answers/{answer_id}/feedback", { params: { path: { answer_id: vars.answerId } }, body: { rating: vars.rating, comment: vars.comment } })),
  });
}

// --- feedback and evaluation --------------------------------------------------------------
export function useFeedbackQueue(ws: string | undefined) {
  return useQuery({
    queryKey: keys.feedback(ws ?? ""),
    queryFn: async () => unwrap(await api.GET("/workspaces/{workspace_id}/feedback", { params: { path: { workspace_id: ws! } } })),
    ...idle(ws),
  });
}
export function usePromoteFeedback(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { feedbackId: string; body: Schemas["PromoteFeedbackRequest"] }) =>
      unwrap(
        await api.POST("/workspaces/{workspace_id}/golden-questions/from-feedback/{feedback_id}", {
          params: { path: { workspace_id: ws, feedback_id: vars.feedbackId } },
          body: vars.body,
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.feedback(ws) });
      void qc.invalidateQueries({ queryKey: keys.golden(ws) });
    },
  });
}
export function useGoldenQuestions(ws: string | undefined) {
  return useQuery({
    queryKey: keys.golden(ws ?? ""),
    queryFn: async () => unwrap(await api.GET("/workspaces/{workspace_id}/golden-questions", { params: { path: { workspace_id: ws! } } })),
    ...idle(ws),
  });
}
export function useEvalRuns(ws: string | undefined) {
  return useQuery({
    queryKey: keys.runs(ws ?? ""),
    queryFn: async () => unwrap(await api.GET("/workspaces/{workspace_id}/eval-runs", { params: { path: { workspace_id: ws! } } })),
    ...idle(ws),
    refetchInterval: (query) => (query.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 2000 : false),
  });
}
export function useCreateEvalRun(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schemas["EvalRunCreate"]) =>
      unwrap(await api.POST("/workspaces/{workspace_id}/eval-runs", { params: { path: { workspace_id: ws } }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.runs(ws) }),
  });
}
export function useCompareRuns(base: string | undefined, head: string | undefined) {
  return useQuery({
    queryKey: keys.compare(base ?? "", head ?? ""),
    queryFn: async () => unwrap(await api.GET("/eval-runs/compare", { params: { query: { base: base!, head: head! } } })),
    enabled: Boolean(base) && Boolean(head) && base !== head,
  });
}
export function useEvalRun(id: string | undefined) {
  return useQuery({
    queryKey: keys.run(id ?? ""),
    queryFn: async () => unwrap(await api.GET("/eval-runs/{run_id}", { params: { path: { run_id: id! } } })),
    ...idle(id),
  });
}
