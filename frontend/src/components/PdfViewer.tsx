import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  useAnnotations,
  useCreateAnnotation,
  useDeleteAnnotation,
  usePdfBytes,
  useUpdateAnnotation,
  type Annotation,
  type AnnotationColor,
  type NormalizedRect,
} from "../api/hooksViewer";
import { locateQuote, normalizeRects, type ItemSpan } from "../lib/pdfQuote";
import { ReadingProgress } from "./ReadingProgress";
import { Button, ErrorBanner, Spinner, inputClass } from "./ui";

// The worker is bundled by Vite and served from our own origin. Nothing is loaded from a CDN: private mode forbids it.
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export const COLORS: Record<AnnotationColor, string> = {
  yellow: "#fde047",
  green: "#86efac",
  blue: "#93c5fd",
  pink: "#f9a8d4",
  orange: "#fdba74",
};
const COLOR_NAMES = Object.keys(COLORS) as AnnotationColor[];
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;
const ZOOM_STEP = 0.25;

interface Pending {
  page: number;
  rects: NormalizedRect[];
  text: string;
}

interface QuoteState {
  status: "searching" | "found" | "missing";
  page?: number;
  spans?: ItemSpan[];
  exact?: boolean;
}

interface Props {
  documentId: string;
  /** The page the citation points at (1-based); the viewer opens there. */
  initialPage?: number | null;
  /** The cited words; they are searched on the page and outlined. */
  quote?: string;
}

const clampZoom = (value: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(value * 100) / 100));

/** Text-layer rectangles of the cited spans, as fractions of the page box. */
function citedRects(textDivs: HTMLElement[], spans: ItemSpan[], pageBox: DOMRect): NormalizedRect[] {
  const raw: DOMRect[] = [];
  for (const span of spans) {
    const el = textDivs[span.item];
    if (!el) continue;
    el.classList.add("pdf-cited");
    const text = el.firstChild;
    if (text && text.nodeType === Node.TEXT_NODE && typeof document.createRange === "function") {
      const range = document.createRange();
      const length = text.textContent?.length ?? 0;
      range.setStart(text, Math.min(span.start, length));
      range.setEnd(text, Math.min(span.end, length));
      if (typeof range.getClientRects === "function") raw.push(...Array.from(range.getClientRects()));
    } else {
      raw.push(el.getBoundingClientRect());
    }
  }
  return normalizeRects(raw, pageBox);
}

function PdfPage({
  pdf,
  pageNumber,
  width,
  aspect,
  quoteSpans,
  annotations,
  onVisible,
}: {
  pdf: PDFDocumentProxy;
  pageNumber: number;
  width: number;
  aspect: number;
  quoteSpans: ItemSpan[] | undefined;
  annotations: Annotation[];
  onVisible: (page: number) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const textDiv = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(typeof IntersectionObserver === "undefined");
  const [cited, setCited] = useState<NormalizedRect[]>([]);

  useEffect(() => {
    const el = wrap.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setNear(true);
          if (entry.isIntersecting && entry.intersectionRatio > 0.5) onVisible(pageNumber);
        }
      },
      { rootMargin: "600px 0px", threshold: [0, 0.5] },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [pageNumber, onVisible]);

  useEffect(() => {
    if (!near || !width) return;
    const life = { cancelled: false };
    const isCancelled = () => life.cancelled; // a call is not narrowed by TS across `await`, a property read is
    let task: { cancel: () => void; promise: Promise<unknown> } | null = null;
    void (async () => {
      const page = await pdf.getPage(pageNumber);
      if (isCancelled()) return;
      const base = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({ scale: width / base.width });
      const dpr = window.devicePixelRatio || 1;
      const c = canvas.current;
      const ctx = c?.getContext("2d");
      if (!c || !ctx) return;
      c.width = Math.floor(viewport.width * dpr);
      c.height = Math.floor(viewport.height * dpr);
      c.style.width = `${viewport.width}px`;
      c.style.height = `${viewport.height}px`;
      task = page.render({ canvasContext: ctx, viewport, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined });
      try {
        await task.promise;
      } catch {
        return; // cancelled by a re-render
      }
      const td = textDiv.current;
      const box = wrap.current;
      if (!td || !box || isCancelled()) return;
      td.replaceChildren();
      td.style.setProperty("--scale-factor", String(viewport.scale));
      const layer = new pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: td, viewport });
      await layer.render();
      if (isCancelled()) return;
      setCited(quoteSpans ? citedRects(layer.textDivs, quoteSpans, box.getBoundingClientRect()) : []);
    })();
    return () => {
      life.cancelled = true;
      task?.cancel();
    };
  }, [pdf, pageNumber, width, near, quoteSpans]);

  return (
    <div
      ref={wrap}
      className="pdf-page"
      data-page={pageNumber}
      style={{ width: width || undefined, height: width ? width * aspect : undefined }}
    >
      <canvas ref={canvas} role="img" aria-label={`Page ${pageNumber}`} />
      <div className="hl-layer" aria-hidden>
        {annotations.flatMap((a) =>
          a.rects.map((r, i) => (
            <div
              key={`${a.id}-${i}`}
              className="pdf-annotation"
              data-annotation-id={a.id}
              style={{ ...rectStyle(r), backgroundColor: COLORS[a.color] }}
            />
          )),
        )}
        {cited.map((r, i) => (
          <div key={i} className="pdf-cite-rect" data-testid="pdf-cite-rect" style={rectStyle(r)} />
        ))}
      </div>
      <div ref={textDiv} className="textLayer" />
      {!near && <div className="grid h-full place-items-center text-xs text-slate-400">Page {pageNumber}</div>}
    </div>
  );
}

const rectStyle = (r: NormalizedRect) => ({
  left: `${r.x * 100}%`,
  top: `${r.y * 100}%`,
  width: `${r.w * 100}%`,
  height: `${r.h * 100}%`,
});

function readSelection(): Pending | null {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
  const range = sel.getRangeAt(0);
  const node = range.commonAncestorContainer;
  const element = node instanceof Element ? node : node.parentElement;
  const pageEl = element?.closest<HTMLElement>(".pdf-page");
  if (!pageEl) return null; // selections across pages are not saved: a highlight belongs to one page
  const rects = normalizeRects(Array.from(range.getClientRects()), pageEl.getBoundingClientRect()).filter((r) => r.h < 0.3);
  const text = sel.toString().replace(/\s+/g, " ").trim().slice(0, 2000);
  if (!rects.length || !text) return null;
  return { page: Number(pageEl.dataset.page), rects, text };
}

export function PdfViewer({ documentId, initialPage, quote }: Props) {
  const bytes = usePdfBytes(documentId);
  const annotationsQuery = useAnnotations(documentId);
  const create = useCreateAnnotation(documentId);
  const update = useUpdateAnnotation(documentId);
  const remove = useDeleteAnnotation(documentId);

  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [aspect, setAspect] = useState(1.414);
  const [zoom, setZoom] = useState(1);
  const [boxWidth, setBoxWidth] = useState(600);
  const [current, setCurrent] = useState(Math.max(1, initialPage ?? 1));
  const [pageField, setPageField] = useState(String(current));
  const [quoteState, setQuoteState] = useState<QuoteState>({ status: quote ? "searching" : "found" });
  const [pending, setPending] = useState<Pending | null>(null);
  const [color, setColor] = useState<AnnotationColor>("yellow");
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editNote, setEditNote] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const lockUntil = useRef(0);

  // --- load the document (bytes come from the authenticated API, never from a URL the browser fetches itself) ------
  useEffect(() => {
    if (!bytes.data) return;
    let cancelled = false;
    // pdf.js transfers the buffer to its worker; hand it a copy so the cached bytes stay usable.
    const task = pdfjs.getDocument({ data: new Uint8Array(bytes.data.slice(0)), isEvalSupported: false, enableXfa: false });
    task.promise
      .then(async (doc) => {
        if (cancelled) {
          void doc.destroy();
          return;
        }
        const first = await doc.getPage(1);
        const view = first.getViewport({ scale: 1 });
        if (cancelled) return;
        setAspect(view.height / view.width);
        setPdf(doc);
      })
      .catch(() => {
        if (!cancelled) setLoadError("The PDF could not be displayed. Use the Text tab instead.");
      });
    return () => {
      cancelled = true;
      void task.destroy();
    };
  }, [bytes.data]);

  const numPages = pdf?.numPages ?? 0;

  // --- layout -----------------------------------------------------------------------------------------------------
  useEffect(() => {
    const el = scroller.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setBoxWidth(el.clientWidth || 600));
    ro.observe(el);
    setBoxWidth(el.clientWidth || 600);
    return () => ro.disconnect();
  }, [pdf]);
  const pageWidth = Math.round(Math.min(Math.max(boxWidth - 24, 280), 900) * zoom);

  const goTo = useCallback(
    (page: number, smooth = false) => {
      const target = Math.min(Math.max(1, page), Math.max(1, numPages));
      setCurrent(target);
      setPageField(String(target));
      lockUntil.current = Date.now() + 600; // ignore the visibility events caused by this very scroll
      const el = scroller.current?.querySelector<HTMLElement>(`[data-page="${target}"]`);
      if (el && scroller.current) scroller.current.scrollTo?.({ top: el.offsetTop - 8, behavior: smooth ? "smooth" : "auto" });
    },
    [numPages],
  );

  // open on the cited page, then on the page where the quote really is
  const opened = useRef(false);
  useEffect(() => {
    if (pdf && !opened.current) {
      opened.current = true;
      goTo(initialPage ?? 1);
    }
  }, [pdf, initialPage, goTo]);

  // keep the scroll position when the zoom changes
  useEffect(() => {
    if (pdf) goTo(current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageWidth]);

  useEffect(() => {
    if (!pdf || !quote) return;
    let cancelled = false;
    void (async () => {
      const wanted = initialPage && initialPage <= pdf.numPages ? initialPage : null;
      const order = wanted
        ? [wanted, wanted + 1, wanted - 1].filter((p) => p >= 1 && p <= pdf.numPages)
        : Array.from({ length: Math.min(pdf.numPages, 300) }, (_, i) => i + 1);
      for (const number of order) {
        try {
          const content = await (await pdf.getPage(number)).getTextContent();
          if (cancelled) return;
          const items = content.items.filter((it) => "str" in it).map((it) => (it as { str: string }).str);
          const match = locateQuote(items, quote);
          if (match) {
            setQuoteState({ status: "found", page: number, spans: match.spans, exact: match.exact });
            goTo(number);
            return;
          }
        } catch {
          // an unreadable page just means no match there
        }
      }
      if (!cancelled) setQuoteState({ status: "missing" });
    })();
    return () => {
      cancelled = true;
    };
  }, [pdf, quote, initialPage, goTo]);

  const onVisible = useCallback((page: number) => {
    if (Date.now() < lockUntil.current) return;
    setCurrent(page);
    setPageField(String(page));
  }, []);

  const commitPageField = () => {
    const n = Number.parseInt(pageField, 10);
    if (Number.isFinite(n)) goTo(n);
    else setPageField(String(current));
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const target = event.target as HTMLElement;
    if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
    switch (event.key) {
      case "PageDown":
      case "ArrowRight":
        event.preventDefault();
        goTo(current + 1, true);
        break;
      case "PageUp":
      case "ArrowLeft":
        event.preventDefault();
        goTo(current - 1, true);
        break;
      case "Home":
        event.preventDefault();
        goTo(1);
        break;
      case "End":
        event.preventDefault();
        goTo(numPages);
        break;
      case "+":
      case "=":
        setZoom((z) => clampZoom(z + ZOOM_STEP));
        break;
      case "-":
        setZoom((z) => clampZoom(z - ZOOM_STEP));
        break;
    }
  };

  const captureSelection = () => setPending(readSelection());

  const annotations = annotationsQuery.data;
  const byPage = useMemo(() => {
    const map = new Map<number, Annotation[]>();
    for (const a of annotations ?? []) map.set(a.page, [...(map.get(a.page) ?? []), a]);
    return map;
  }, [annotations]);

  const save = () => {
    if (!pending) return;
    create.mutate(
      { page: pending.page, rects: pending.rects, text: pending.text, note: note.trim(), color },
      {
        onSuccess: () => {
          setPending(null);
          setNote("");
          window.getSelection()?.removeAllRanges();
        },
      },
    );
  };

  if (loadError) return <div className="p-4"><ErrorBanner error={new Error(loadError)} /></div>;
  if (bytes.error) return <div className="p-4"><ErrorBanner error={bytes.error} /></div>;
  if (!pdf) {
    return (
      <div className="grid h-64 place-items-center">
        <Spinner label="Loading the PDF…" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="pdf-viewer">
      <div role="toolbar" aria-label="PDF controls" className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2 text-sm">
        <Button variant="secondary" className="px-2.5 py-1" onClick={() => goTo(current - 1, true)} disabled={current <= 1} aria-label="Previous page">
          ‹
        </Button>
        <label className="flex shrink-0 items-center gap-1 whitespace-nowrap text-slate-600">
          <span className="sr-only">Go to page</span>
          <input
            type="number"
            min={1}
            max={numPages}
            value={pageField}
            aria-label="Go to page"
            className={`${inputClass} w-16 px-2 py-1`}
            onChange={(event) => setPageField(event.target.value)}
            onBlur={commitPageField}
            onKeyDown={(event) => {
              if (event.key === "Enter") commitPageField();
            }}
          />
          <span aria-hidden>/ {numPages}</span>
        </label>
        <Button variant="secondary" className="px-2.5 py-1" onClick={() => goTo(current + 1, true)} disabled={current >= numPages} aria-label="Next page">
          ›
        </Button>
        <span className="sr-only" role="status" aria-live="polite">
          Page {current} of {numPages}
        </span>
        {numPages > 0 && (
          <div className="order-last w-full sm:order-none sm:ml-auto sm:w-44">
            <ReadingProgress documentId={documentId} page={current} pageCount={numPages} compact />
          </div>
        )}
        <span className="mx-1 h-5 w-px bg-slate-300" aria-hidden />
        <Button variant="secondary" className="px-2.5 py-1" onClick={() => setZoom((z) => clampZoom(z - ZOOM_STEP))} disabled={zoom <= MIN_ZOOM} aria-label="Zoom out">
          −
        </Button>
        <span className="w-12 text-center tabular-nums text-slate-600" data-testid="zoom-level">
          {Math.round(zoom * 100)}%
        </span>
        <Button variant="secondary" className="px-2.5 py-1" onClick={() => setZoom((z) => clampZoom(z + ZOOM_STEP))} disabled={zoom >= MAX_ZOOM} aria-label="Zoom in">
          +
        </Button>
        <Button variant="secondary" className="px-2.5 py-1" onClick={() => setZoom(1)} aria-label="Fit to width">
          Fit
        </Button>
      </div>

      {quoteState.status === "missing" && (
        <p role="status" className="border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-800">
          Could not locate the quote on the page; showing the page.
        </p>
      )}
      {quoteState.status === "found" && quoteState.exact === false && (
        <p role="status" className="border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-800">
          The page text differs slightly from the stored text; the closest match is outlined.
        </p>
      )}

      {pending && (
        <div role="group" aria-label="Save highlight" className="space-y-2 border-b border-slate-200 bg-white px-3 py-2 text-sm shadow-sm">
          <p className="line-clamp-2 text-slate-600">“{pending.text}”</p>
          <div className="flex flex-wrap items-center gap-2">
            <div role="radiogroup" aria-label="Highlight colour" className="flex gap-1.5">
              {COLOR_NAMES.map((name) => (
                <button
                  key={name}
                  type="button"
                  role="radio"
                  aria-checked={color === name}
                  aria-label={name}
                  title={name}
                  onClick={() => setColor(name)}
                  className={`h-6 w-6 rounded-full border-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${color === name ? "border-slate-800" : "border-white shadow ring-1 ring-slate-300"}`}
                  style={{ backgroundColor: COLORS[name] }}
                />
              ))}
            </div>
            <input
              type="text"
              aria-label="Note (optional)"
              placeholder="Note (optional)"
              value={note}
              maxLength={2000}
              onChange={(event) => setNote(event.target.value)}
              className={`${inputClass} min-w-40 flex-1 py-1`}
            />
            <Button onClick={save} disabled={create.isPending} className="py-1">
              Save highlight
            </Button>
            <Button variant="ghost" onClick={() => setPending(null)} className="py-1">
              Cancel
            </Button>
          </div>
          <ErrorBanner error={create.error} />
        </div>
      )}

      <div
        ref={scroller}
        role="region"
        aria-label="PDF pages"
        tabIndex={0}
        onKeyDown={onKeyDown}
        onMouseUp={captureSelection}
        onKeyUp={(event) => event.shiftKey && captureSelection()}
        className="relative min-h-0 flex-1 overflow-auto bg-slate-200/70 py-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500"
      >
        {Array.from({ length: numPages }, (_, i) => i + 1).map((n) => (
          <PdfPage
            key={n}
            pdf={pdf}
            pageNumber={n}
            width={pageWidth}
            aspect={aspect}
            quoteSpans={quoteState.page === n ? quoteState.spans : undefined}
            annotations={byPage.get(n) ?? []}
            onVisible={onVisible}
          />
        ))}
      </div>

      <section aria-label="Your highlights" className="max-h-44 shrink-0 overflow-y-auto border-t border-slate-200 bg-white px-3 py-2 text-sm">
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Your highlights ({annotations?.length ?? 0})
        </h3>
        <ErrorBanner error={annotationsQuery.error ?? update.error ?? remove.error} />
        {annotations?.length === 0 && <p className="text-xs text-slate-400">Select text in the PDF to save a highlight. Only you can see it.</p>}
        <ul className="space-y-1.5">
          {annotations?.map((a) => (
            <li key={a.id} className="flex items-start gap-2" data-testid="annotation-item">
              <span className="mt-1 h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: COLORS[a.color] }} aria-hidden />
              <div className="min-w-0 flex-1">
                <button type="button" className="block max-w-full truncate text-left text-slate-800 hover:underline" onClick={() => goTo(a.page, true)}>
                  p. {a.page}: “{a.text}”
                </button>
                {editing === a.id ? (
                  <div className="mt-1 flex gap-1.5">
                    <input
                      type="text"
                      aria-label={`Note for the highlight on page ${a.page}`}
                      value={editNote}
                      maxLength={2000}
                      onChange={(event) => setEditNote(event.target.value)}
                      className={`${inputClass} py-1`}
                    />
                    <Button
                      className="py-1"
                      disabled={update.isPending}
                      onClick={() => update.mutate({ id: a.id, note: editNote.trim() }, { onSuccess: () => setEditing(null) })}
                    >
                      Save note
                    </Button>
                    <Button variant="ghost" className="py-1" onClick={() => setEditing(null)}>
                      Cancel
                    </Button>
                  </div>
                ) : (
                  a.note && <p className="text-xs text-slate-500">{a.note}</p>
                )}
              </div>
              {editing !== a.id && (
                <div className="flex shrink-0 gap-1">
                  <Button
                    variant="ghost"
                    className="px-2 py-0.5 text-xs"
                    aria-label={`Edit note on page ${a.page}`}
                    onClick={() => {
                      setEditing(a.id);
                      setEditNote(a.note);
                    }}
                  >
                    Edit
                  </Button>
                  <Button variant="ghost" className="px-2 py-0.5 text-xs text-red-600" aria-label={`Delete highlight on page ${a.page}`} onClick={() => remove.mutate(a.id)}>
                    Delete
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
