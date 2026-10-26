/** TanStack Query hooks for the learning layer (reading progress, study sets, plans, summarize/compare). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "./client";

export type ReadingProgress = Schemas["ReadingProgress"];
export type ReadingProgressUpdate = Schemas["ReadingProgressUpdate"];
export type ReadingProgressItem = Schemas["ReadingProgressItem"];
export type StudySet = Schemas["StudySet"];
export type StudySetDetail = Schemas["StudySetDetail"];
export type StudySetItem = Schemas["StudySetItem"];
export type LearningPlan = Schemas["LearningPlan"];
export type LearningPlanSummary = Schemas["LearningPlanSummary"];
export type PlanStep = Schemas["PlanStep"];

export const learnKeys = {
  progress: (document: string) => ["learn", "progress", document] as const,
  recent: (ws: string) => ["learn", "recent", ws] as const,
  sets: (ws: string) => ["learn", "sets", ws] as const,
  set: (id: string) => ["learn", "set", id] as const,
  plans: (ws: string) => ["learn", "plans", ws] as const,
  plan: (id: string) => ["learn", "plan", id] as const,
};

const gone = (result: { error?: unknown; response: Response }) => {
  if (result.error) unwrap(result as never);
};

// --- reading progress ---------------------------------------------------------------------
export function useReadingProgress(documentId: string | undefined) {
  return useQuery({
    queryKey: learnKeys.progress(documentId ?? ""),
    queryFn: async () => unwrap(await api.GET("/documents/{document_id}/progress", { params: { path: { document_id: documentId! } } })),
    enabled: Boolean(documentId),
  });
}
export function useUpdateReadingProgress(documentId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Partial<ReadingProgressUpdate>) => {
      if (!documentId) throw new Error("No document");
      return unwrap(
        await api.PUT("/documents/{document_id}/progress", {
          params: { path: { document_id: documentId } },
          body: { mark_read: false, ...body },
        }),
      );
    },
    onSuccess: (data) => {
      qc.setQueryData(learnKeys.progress(data.document_id), data);
      void qc.invalidateQueries({ queryKey: ["learn", "recent"] });
      void qc.invalidateQueries({ queryKey: ["learn", "set"] });
      void qc.invalidateQueries({ queryKey: ["learn", "sets"] });
      void qc.invalidateQueries({ queryKey: ["learn", "plan"] });
    },
  });
}
export function useResetReadingProgress(documentId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      if (!documentId) throw new Error("No document");
      gone(await api.DELETE("/documents/{document_id}/progress", { params: { path: { document_id: documentId } } }));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["learn"] }),
  });
}
export function useRecentReading(ws: string | undefined) {
  return useQuery({
    queryKey: learnKeys.recent(ws ?? ""),
    queryFn: async () => unwrap(await api.GET("/workspaces/{workspace_id}/reading-progress", { params: { path: { workspace_id: ws! } } })),
    enabled: Boolean(ws),
  });
}

// --- study sets ---------------------------------------------------------------------------
export function useStudySets(ws: string | undefined) {
  return useQuery({
    queryKey: learnKeys.sets(ws ?? ""),
    queryFn: async () => unwrap(await api.GET("/workspaces/{workspace_id}/study-sets", { params: { path: { workspace_id: ws! } } })),
    enabled: Boolean(ws),
  });
}
export function useStudySet(id: string | undefined) {
  return useQuery({
    queryKey: learnKeys.set(id ?? ""),
    queryFn: async () => unwrap(await api.GET("/study-sets/{study_set_id}", { params: { path: { study_set_id: id! } } })),
    enabled: Boolean(id),
  });
}
export function useCreateStudySet(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { name: string; description?: string }) =>
      unwrap(await api.POST("/workspaces/{workspace_id}/study-sets", { params: { path: { workspace_id: ws } }, body: { description: "", ...body } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: learnKeys.sets(ws) }),
  });
}
export function useUpdateStudySet(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Schemas["StudySetUpdate"]) =>
      unwrap(await api.PATCH("/study-sets/{study_set_id}", { params: { path: { study_set_id: id } }, body })),
    onSuccess: (data) => {
      qc.setQueryData(learnKeys.set(id), data);
      void qc.invalidateQueries({ queryKey: learnKeys.sets(data.workspace_id) });
    },
  });
}
export function useDeleteStudySet(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => gone(await api.DELETE("/study-sets/{study_set_id}", { params: { path: { study_set_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: learnKeys.sets(ws) }),
  });
}
export function useAddStudySetItem(setId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { document_id?: string; reference?: Schemas["ReferenceInput"]; note?: string }) =>
      unwrap(await api.POST("/study-sets/{study_set_id}/items", { params: { path: { study_set_id: setId } }, body: { note: "", ...body } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["learn"] }),
  });
}
export function useUpdateStudySetItem(setId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { itemId: string; body: Schemas["StudySetItemUpdate"] }) =>
      unwrap(
        await api.PATCH("/study-sets/{study_set_id}/items/{item_id}", {
          params: { path: { study_set_id: setId, item_id: vars.itemId } },
          body: vars.body,
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: learnKeys.set(setId) }),
  });
}
export function useRemoveStudySetItem(setId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (itemId: string) =>
      gone(await api.DELETE("/study-sets/{study_set_id}/items/{item_id}", { params: { path: { study_set_id: setId, item_id: itemId } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["learn"] }),
  });
}

// --- learning plans -----------------------------------------------------------------------
export function useLearningPlans(ws: string | undefined) {
  return useQuery({
    queryKey: learnKeys.plans(ws ?? ""),
    queryFn: async () => unwrap(await api.GET("/workspaces/{workspace_id}/learning-plans", { params: { path: { workspace_id: ws! } } })),
    enabled: Boolean(ws),
  });
}
export function useLearningPlan(id: string | undefined) {
  return useQuery({
    queryKey: learnKeys.plan(id ?? ""),
    queryFn: async () => unwrap(await api.GET("/learning-plans/{plan_id}", { params: { path: { plan_id: id! } } })),
    enabled: Boolean(id),
  });
}
export function useCreateLearningPlan(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { title?: string | null; study_set_id?: string | null; topic?: string | null; document_ids?: string[]; hours_per_week?: number }) =>
      unwrap(await api.POST("/workspaces/{workspace_id}/learning-plans", { params: { path: { workspace_id: ws } }, body: { hours_per_week: 4, ...body } })),
    onSuccess: (data) => {
      qc.setQueryData(learnKeys.plan(data.id), data);
      void qc.invalidateQueries({ queryKey: learnKeys.plans(ws) });
    },
  });
}
export function useDeletePlan(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => gone(await api.DELETE("/learning-plans/{plan_id}", { params: { path: { plan_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: learnKeys.plans(ws) }),
  });
}
export function useSetPlanStepDone(planId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { stepId: string; done: boolean }) =>
      unwrap(
        await api.PATCH("/learning-plans/{plan_id}/steps/{step_id}", {
          params: { path: { plan_id: planId, step_id: vars.stepId } },
          body: { done: vars.done },
        }),
      ),
    onSuccess: (data) => {
      qc.setQueryData(learnKeys.plan(planId), data);
      void qc.invalidateQueries({ queryKey: learnKeys.plans(data.workspace_id) });
    },
  });
}

// --- summarize and compare ----------------------------------------------------------------
export function useSummarize(ws: string) {
  return useMutation({
    mutationFn: async (body: { document_id: string; focus?: string | null }) =>
      unwrap(await api.POST("/workspaces/{workspace_id}/learning/summarize", { params: { path: { workspace_id: ws } }, body })),
  });
}
export function useCompare(ws: string) {
  return useMutation({
    mutationFn: async (body: { document_ids: string[]; aspect: string }) =>
      unwrap(await api.POST("/workspaces/{workspace_id}/learning/compare", { params: { path: { workspace_id: ws } }, body })),
  });
}
