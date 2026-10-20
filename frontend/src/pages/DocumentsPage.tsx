import { useEffect, useRef, useState } from "react";
import { useCollections, useDeleteDocument, useDocuments, useReindexDocument, useUploadDocument } from "../api/hooks";
import { useWorkspace } from "../auth/WorkspaceContext";
import { Badge, Button, Card, Empty, ErrorBanner, Spinner } from "../components/ui";

export function DocumentsPage() {
  const { current, isAdmin } = useWorkspace();
  const collections = useCollections(current?.id);
  const [selected, setSelected] = useState<string | undefined>();

  useEffect(() => {
    if (!selected && collections.data?.[0]) setSelected(collections.data[0].id);
  }, [collections.data, selected]);

  const collection = collections.data?.find((c) => c.id === selected);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-slate-900">Documents</h1>
      <ErrorBanner error={collections.error} />
      {collections.isLoading && <Spinner />}
      {collections.data?.length === 0 && <Empty>No collections yet. {isAdmin ? "Create one on the Workspace page." : "Ask an admin to create one."}</Empty>}

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Collections">
        {collections.data?.map((c) => (
          <button
            key={c.id}
            role="tab"
            aria-selected={c.id === selected}
            onClick={() => setSelected(c.id)}
            className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm ${c.id === selected ? "border-indigo-300 bg-indigo-50 text-indigo-800" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"}`}
          >
            {c.name}
            <Badge value={c.visibility} />
          </button>
        ))}
      </div>

      {collection && <CollectionDocuments collectionId={collection.id} canEdit={isAdmin} />}
    </div>
  );
}

function CollectionDocuments({ collectionId, canEdit }: { collectionId: string; canEdit: boolean }) {
  const documents = useDocuments(collectionId);
  const upload = useUploadDocument(collectionId);
  const remove = useDeleteDocument(collectionId);
  const reindex = useReindexDocument(collectionId);
  const input = useRef<HTMLInputElement>(null);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);

  async function onFiles(files: FileList | null) {
    if (!files) return;
    const errors: string[] = [];
    for (const file of Array.from(files)) {
      try {
        await upload.mutateAsync(file);
      } catch (error) {
        errors.push(`${file.name}: ${error instanceof Error ? error.message : "upload failed"}`);
      }
    }
    setUploadErrors(errors);
    if (input.current) input.current.value = "";
  }

  return (
    <Card
      title="Files"
      actions={
        canEdit && (
          <>
            <input ref={input} type="file" multiple accept=".pdf,.docx,.md,.markdown,.html,.htm,.txt" hidden aria-label="Upload files" onChange={(e) => void onFiles(e.target.files)} />
            <Button onClick={() => input.current?.click()} disabled={upload.isPending}>
              {upload.isPending ? "Uploading…" : "Upload documents"}
            </Button>
          </>
        )
      }
    >
      {uploadErrors.map((message) => (
        <ErrorBanner key={message} error={new Error(message)} />
      ))}
      <ErrorBanner error={documents.error ?? remove.error ?? reindex.error} />
      {documents.isLoading && <Spinner />}
      {documents.data?.length === 0 && <Empty>No documents in this collection yet.</Empty>}
      {documents.data && documents.data.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="py-2">Title</th>
              <th>Status</th>
              <th>Chunks</th>
              <th>Type</th>
              {canEdit && <th className="text-right">Actions</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {documents.data.map((doc) => (
              <tr key={doc.id}>
                <td className="py-2 pr-2">
                  <div className="font-medium text-slate-900">{doc.title}</div>
                  <div className="text-xs text-slate-400">{doc.filename}</div>
                  {doc.error && <div className="text-xs text-red-600">{doc.error}</div>}
                </td>
                <td>
                  <Badge value={doc.status} />
                </td>
                <td>{doc.chunk_count}</td>
                <td className="text-slate-500">{doc.mime.split("/")[1]?.split(".").pop()}</td>
                {canEdit && (
                  <td className="space-x-1 text-right">
                    <Button variant="secondary" onClick={() => reindex.mutate(doc.id)} disabled={reindex.isPending}>
                      Reindex
                    </Button>
                    <Button
                      variant="danger"
                      onClick={() => {
                        if (window.confirm(`Delete "${doc.title}"? Its chunks and the stored file are removed.`)) remove.mutate(doc.id);
                      }}
                    >
                      Delete
                    </Button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
