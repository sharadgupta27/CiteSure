import { useEffect, useRef, useState } from "react";
import { downloadDocument, type Citation } from "../api/client";
import { useDocumentChunks } from "../api/hooks";
import { describeLocation, safeHref } from "../lib/citations";
import { segmentText } from "../lib/highlight";
import { Button, ErrorBanner, Spinner } from "./ui";

interface Props {
  citation: Citation | null;
  onClose: () => void;
}

/** A side drawer showing the cited chunk with the quoted words highlighted, plus the rest of the document. */
export function SourceViewer({ citation, onClose }: Props) {
  const isPublic = citation?.source_type === "public";
  // A public source is a paper or web page, not a stored document: there are no chunks to load or file to download.
  const chunks = useDocumentChunks(isPublic ? undefined : citation?.document_id);
  const [showAll, setShowAll] = useState(false);
  const [downloadError, setDownloadError] = useState<unknown>(null);
  const markRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!citation) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [citation, onClose]);

  useEffect(() => {
    markRef.current?.scrollIntoView?.({ block: "center" });
  }, [chunks.data, citation]);

  if (!citation) return null;
  if (isPublic) return <PublicSource citation={citation} onClose={onClose} />;

  const hasQuote = citation.quote_end > citation.quote_start;
  const visible = chunks.data?.filter((c) => showAll || c.id === citation.chunk_id) ?? [];

  async function openOriginal() {
    if (!citation) return;
    try {
      const { blob, filename } = await downloadDocument(citation.document_id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setDownloadError(error);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Source"
        className="flex h-full w-full max-w-xl flex-col bg-white shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 p-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">{citation.document_title}</h2>
            <p className="text-sm text-slate-500">{describeLocation(citation)}</p>
          </div>
          <Button variant="ghost" onClick={onClose} aria-label="Close source">
            ✕
          </Button>
        </header>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {chunks.isLoading && <Spinner label="Loading the source…" />}
          <ErrorBanner error={chunks.error ?? downloadError} />
          {visible.map((chunk) => {
            const isCited = chunk.id === citation.chunk_id;
            const ranges = isCited && hasQuote ? [{ start: citation.quote_start, end: citation.quote_end }] : [];
            return (
              <article key={chunk.id} className={isCited ? "rounded-md border border-indigo-200 bg-indigo-50/40 p-3" : "p-3 text-slate-500"}>
                <p className="mb-1 text-xs uppercase tracking-wide text-slate-400">
                  {chunk.heading_path.join(" › ") || "Section"} {chunk.page_start != null && `· page ${chunk.page_start}`}
                </p>
                <p className="whitespace-pre-wrap leading-7" data-testid={isCited ? "cited-chunk" : undefined}>
                  {segmentText(chunk.text, ranges).map((segment, i) =>
                    segment.highlighted ? (
                      <mark key={i} className="cite" ref={markRef}>
                        {segment.text}
                      </mark>
                    ) : (
                      <span key={i}>{segment.text}</span>
                    ),
                  )}
                </p>
              </article>
            );
          })}
        </div>
        <footer className="flex items-center justify-between gap-2 border-t border-slate-200 p-3">
          <Button variant="secondary" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Show only the cited passage" : "Show the whole document"}
          </Button>
          <Button variant="secondary" onClick={openOriginal}>
            Download original
          </Button>
        </footer>
      </aside>
    </div>
  );
}

function PublicSource({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const href = safeHref(citation.url);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Source"
        className="flex h-full w-full max-w-xl flex-col bg-white shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 p-4">
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-emerald-700">Public source</p>
            <h2 className="text-base font-semibold text-slate-900">{citation.document_title}</h2>
            <p className="text-sm text-slate-500">{describeLocation(citation)}</p>
          </div>
          <Button variant="ghost" onClick={onClose} aria-label="Close source">
            ✕
          </Button>
        </header>
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          <p className="text-sm text-slate-500">The cited passage, exactly as published:</p>
          <blockquote className="rounded-md border border-emerald-200 bg-emerald-50/50 p-3 leading-7" data-testid="cited-chunk">
            <mark className="cite">{citation.quote}</mark>
          </blockquote>
        </div>
        <footer className="flex items-center justify-end gap-2 border-t border-slate-200 p-3">
          {href ? (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Open the original ↗
            </a>
          ) : (
            <span className="text-sm text-slate-400">No address available</span>
          )}
        </footer>
      </aside>
    </div>
  );
}
