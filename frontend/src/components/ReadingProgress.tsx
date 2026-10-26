import { useCallback, useEffect, useRef } from "react";
import { useReadingProgress, useResetReadingProgress, useUpdateReadingProgress, type ReadingProgress as Progress } from "../api/hooksLearning";
import { ProgressBar } from "./learn/ProgressBar";
import { Button } from "./ui";

const SAVE_DEBOUNCE_MS = 400;
export const DEFAULT_DWELL_MS = 4000;

interface TrackOptions {
  documentId: string;
  page: number | null;
  pageCount: number | null;
  /** How long a page must stay on screen before it counts as read. */
  dwellMs?: number;
}

/**
 * Reports the page being read to the server and marks it read once it has been shown for `dwellMs`.
 * Nothing is sent without a document id or a page. Call it from a viewer, or use <ReadingProgress /> which wraps it.
 */
export function useTrackReading({ documentId, page, pageCount, dwellMs = DEFAULT_DWELL_MS }: TrackOptions) {
  const progress = useReadingProgress(documentId || undefined);
  const update = useUpdateReadingProgress(documentId || undefined);
  const reset = useResetReadingProgress(documentId || undefined);
  const send = useRef(update.mutate);
  send.current = update.mutate;

  useEffect(() => {
    if (!documentId || page == null || page < 1) return;
    const clamped = pageCount ? Math.min(page, pageCount) : page;
    const save = setTimeout(() => send.current({ page: clamped }), SAVE_DEBOUNCE_MS);
    const read = setTimeout(() => send.current({ page: clamped, mark_read: true }), dwellMs);
    return () => {
      clearTimeout(save);
      clearTimeout(read);
    };
  }, [documentId, page, pageCount, dwellMs]);

  const markRead = useCallback(() => {
    if (documentId && page != null && page >= 1) send.current({ page, mark_read: true });
  }, [documentId, page]);

  return { progress: progress.data, isLoading: progress.isLoading, error: progress.error, markRead, reset: reset.mutate, isSaving: update.isPending };
}

interface Props {
  documentId: string;
  page: number | null;
  pageCount: number | null;
  onChange?: (progress: Progress) => void;
  dwellMs?: number;
  compact?: boolean;
}

/** Progress bar plus the tracking behaviour. The viewer renders it next to the document; it owns no layout. */
export function ReadingProgress({ documentId, page, pageCount, onChange, dwellMs, compact = false }: Props) {
  const { progress, markRead, reset } = useTrackReading({ documentId, page, pageCount, dwellMs });
  const notified = useRef<string | null>(null);

  useEffect(() => {
    if (progress && onChange && notified.current !== progress.updated_at) {
      notified.current = progress.updated_at;
      onChange(progress);
    }
  }, [progress, onChange]);

  if (!documentId) return null;
  const percent = progress?.percent ?? 0;
  const total = pageCount ?? null;
  const summary = total && page ? `Page ${page} of ${total} - ${Math.round(percent)}% read` : `${Math.round(percent)}% read`;

  return (
    <div className="space-y-1.5" data-testid="reading-progress">
      <div className="flex items-center justify-between gap-2 text-xs text-slate-600">
        <span>{summary}</span>
        {!compact && (
          <span className="flex gap-1.5">
            <Button type="button" variant="secondary" className="!px-2 !py-1 text-xs" disabled={page == null} onClick={markRead}>
              Mark page as read
            </Button>
            <Button type="button" variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => reset()}>
              Reset
            </Button>
          </span>
        )}
      </div>
      <ProgressBar percent={percent} label="Reading progress" />
    </div>
  );
}
