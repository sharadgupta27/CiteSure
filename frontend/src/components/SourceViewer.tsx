import { lazy, Suspense, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { downloadDocument, type Citation } from "../api/client";
import { useDocumentChunks } from "../api/hooks";
import { useViewerDocument } from "../api/hooksViewer";
import { describeLocation, safeHref } from "../lib/citations";
import { segmentText } from "../lib/highlight";
import { PublicSourceActions } from "./PublicSourceActions";
import { Button, ErrorBanner, Spinner } from "./ui";

// pdf.js is large: it is only downloaded (from our own origin) when a PDF is actually opened.
const PdfViewer = lazy(() => import("./PdfViewer").then((m) => ({ default: m.PdfViewer })));

type Tab = "pdf" | "text";
const TABS: { id: Tab; label: string }[] = [
  { id: "pdf", label: "PDF" },
  { id: "text", label: "Text" },
];

interface Props {
  citation: Citation | null;
  onClose: () => void;
}

/**
 * A side drawer showing the cited chunk with the quoted words highlighted, plus the rest of the document.
 * For a PDF it also offers the real page with the quote outlined and the reader's own highlights (the PDF tab).
 */
export function SourceViewer({ citation, onClose }: Props) {
  const isPublic = citation?.source_type === "public";
  // A public source is a paper or web page, not a stored document: there are no chunks to load or file to download.
  const chunks = useDocumentChunks(isPublic ? undefined : citation?.document_id);
  const [showAll, setShowAll] = useState(false);
  const [downloadError, setDownloadError] = useState<unknown>(null);
  const markRef = useRef<HTMLElement | null>(null);
  // Only documents with page numbers can be PDFs: ask for the record (and its mime type) just for those.
  const paged = citation?.page_start != null || Boolean(chunks.data?.some((c) => c.page_start != null));
  const record = useViewerDocument(isPublic ? undefined : citation?.document_id, paged);
  const isPdf = record.data?.mime === "application/pdf";
  const [chosenTab, setChosenTab] = useState<Tab>("pdf");
  const tab: Tab = isPdf ? chosenTab : "text";

  useEffect(() => {
    if (!citation) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      // Escape inside the note field of the PDF viewer must not throw the reader's draft away with the drawer.
      const target = event.target as HTMLElement | null;
      if (event.key === "Escape" && target?.tagName !== "INPUT" && target?.tagName !== "TEXTAREA") onClose();
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

  function onTabKey(event: KeyboardEvent<HTMLDivElement>) {
    const index = TABS.findIndex((t) => t.id === tab);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = TABS.length - 1;
    else return;
    event.preventDefault();
    const target = TABS[next];
    if (!target) return;
    setChosenTab(target.id);
    document.getElementById(`source-tab-${target.id}`)?.focus();
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Source"
        className={`flex h-full w-full flex-col bg-white shadow-xl ${tab === "pdf" ? "max-w-3xl" : "max-w-xl"}`}
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
        {isPdf && (
          <div role="tablist" aria-label="Source view" className="flex gap-1 border-b border-slate-200 px-4 pt-2" onKeyDown={onTabKey}>
            {TABS.map((t) => (
              <button
                key={t.id}
                id={`source-tab-${t.id}`}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                aria-controls={`source-panel-${t.id}`}
                tabIndex={tab === t.id ? 0 : -1}
                onClick={() => setChosenTab(t.id)}
                className={`-mb-px rounded-t-lg border-b-2 px-3 py-1.5 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${tab === t.id ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
        {tab === "pdf" && (
          <div role="tabpanel" id="source-panel-pdf" aria-labelledby="source-tab-pdf" className="min-h-0 flex-1">
            <Suspense fallback={<div className="p-4"><Spinner label="Loading the viewer…" /></div>}>
              <PdfViewer
                key={`${citation.document_id}:${citation.chunk_id}`}
                documentId={citation.document_id}
                initialPage={citation.page_start}
                quote={citation.quote}
              />
            </Suspense>
          </div>
        )}
        <div
          className={`flex-1 space-y-4 overflow-y-auto p-4 ${tab === "pdf" ? "hidden" : ""}`}
          {...(isPdf ? { role: "tabpanel", id: "source-panel-text", "aria-labelledby": "source-tab-text" } : {})}
        >
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
          {tab === "text" ? (
            <Button variant="secondary" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show only the cited passage" : "Show the whole document"}
            </Button>
          ) : (
            <span />
          )}
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
          <PublicSourceActions citation={citation} />
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
