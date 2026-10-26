/** Hooks for the PDF viewer: the document record, its bytes, and the caller's own annotations. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE, ApiError, api, getAuthToken, unwrap, type Schemas } from "./client";

export type Annotation = Schemas["Annotation"];
export type AnnotationCreate = Schemas["AnnotationCreate"];
export type AnnotationColor = Schemas["AnnotationColor"];
export type NormalizedRect = Schemas["NormalizedRect"];

export const viewerKeys = {
  document: (id: string) => ["viewer-document", id] as const,
  bytes: (id: string) => ["viewer-bytes", id] as const,
  annotations: (id: string) => ["annotations", id] as const,
};

/** The document record (its mime type decides whether the PDF tab exists). */
export function useViewerDocument(documentId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: viewerKeys.document(documentId ?? ""),
    queryFn: async () => unwrap(await api.GET("/documents/{document_id}", { params: { path: { document_id: documentId! } } })),
    enabled: Boolean(documentId) && enabled,
    retry: false,
  });
}

/** The original file through the authenticated download endpoint. Same origin only: nothing is fetched from a CDN. */
export async function fetchDocumentBytes(documentId: string): Promise<ArrayBuffer> {
  const token = getAuthToken();
  const response = await fetch(`${API_BASE}/documents/${documentId}/file`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new ApiError(response.status, "download_failed", "Could not load the PDF");
  return response.arrayBuffer();
}

export function usePdfBytes(documentId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: viewerKeys.bytes(documentId ?? ""),
    queryFn: () => fetchDocumentBytes(documentId!),
    enabled: Boolean(documentId) && enabled,
    staleTime: Infinity,
    gcTime: 60_000,
    retry: false,
  });
}

export function useAnnotations(documentId: string | undefined) {
  return useQuery({
    queryKey: viewerKeys.annotations(documentId ?? ""),
    queryFn: async () =>
      unwrap(await api.GET("/documents/{document_id}/annotations", { params: { path: { document_id: documentId! } } })),
    enabled: Boolean(documentId),
    retry: false,
  });
}

export function useCreateAnnotation(documentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: AnnotationCreate) =>
      unwrap(await api.POST("/documents/{document_id}/annotations", { params: { path: { document_id: documentId } }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: viewerKeys.annotations(documentId) }),
  });
}

export function useUpdateAnnotation(documentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { id: string; note?: string; color?: AnnotationColor }) => {
      const { id, ...body } = vars;
      return unwrap(await api.PATCH("/annotations/{annotation_id}", { params: { path: { annotation_id: id } }, body }));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: viewerKeys.annotations(documentId) }),
  });
}

export function useDeleteAnnotation(documentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const result = await api.DELETE("/annotations/{annotation_id}", { params: { path: { annotation_id: id } } });
      if (result.error) unwrap(result as never);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: viewerKeys.annotations(documentId) }),
  });
}
