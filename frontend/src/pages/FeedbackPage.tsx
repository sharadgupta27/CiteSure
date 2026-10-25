import { useState, type FormEvent } from "react";
import type { Schemas } from "../api/client";
import { useFeedbackQueue, usePromoteFeedback } from "../api/hooks";
import { useWorkspace } from "../auth/WorkspaceContext";
import { Badge, Button, Card, Empty, ErrorBanner, Field, Spinner, inputClass } from "../components/ui";

type FeedbackItem = Schemas["FeedbackItem"];

export function FeedbackPage() {
  const { current } = useWorkspace();
  const queue = useFeedbackQueue(current?.id);
  const [promoting, setPromoting] = useState<FeedbackItem | null>(null);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight text-slate-900">Feedback queue</h1>
      <p className="max-w-3xl text-sm text-slate-600">
        Thumbs-down answers from your colleagues. Promote a good example to the <strong>golden set</strong> so the next evaluation run checks that the
        problem stays fixed.
      </p>
      <ErrorBanner error={queue.error} />
      {queue.isLoading && <Spinner />}
      {queue.data?.length === 0 && <Empty>No feedback yet.</Empty>}
      <ul className="space-y-3">
        {queue.data?.map((item) => (
          <li key={item.id}>
            <Card>
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <p className="font-medium text-slate-900">{item.question}</p>
                  <p className="flex items-center gap-2 text-sm text-slate-500">
                    <span aria-label={item.rating === 1 ? "thumbs up" : "thumbs down"}>{item.rating === 1 ? "👍" : "👎"}</span>
                    <Badge value={item.answer_status} />
                    {item.promoted && <Badge value="done" />}
                    {item.promoted && <span className="text-xs">in golden set</span>}
                  </p>
                  {item.comment && <p className="text-sm text-slate-700">“{item.comment}”</p>}
                </div>
                {!item.promoted && (
                  <Button variant="secondary" onClick={() => setPromoting(item)}>
                    Add to golden set
                  </Button>
                )}
              </div>
            </Card>
          </li>
        ))}
      </ul>
      {promoting && current && <PromoteDialog workspaceId={current.id} item={promoting} onClose={() => setPromoting(null)} />}
    </div>
  );
}

function PromoteDialog({ workspaceId, item, onClose }: { workspaceId: string; item: FeedbackItem; onClose: () => void }) {
  const promote = usePromoteFeedback(workspaceId);
  const [answerable, setAnswerable] = useState(true);
  const [expectedAnswer, setExpectedAnswer] = useState("");
  const [document, setDocument] = useState("");
  const [quote, setQuote] = useState("");
  const [askAs, setAskAs] = useState("");
  const [reason, setReason] = useState(item.comment ?? "");

  function submit(event: FormEvent) {
    event.preventDefault();
    promote.mutate(
      {
        feedbackId: item.id,
        body: {
          answerable,
          expected_answer: answerable ? expectedAnswer.trim() || null : null,
          expected_quotes: answerable && document && quote ? [{ document: document.trim(), quote: quote.trim() }] : [],
          ask_as: askAs.trim() || null,
          reason: reason.trim(),
        },
      },
      { onSuccess: onClose },
    );
  }

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-slate-900/30 p-4" onClick={onClose}>
      <form
        role="dialog"
        aria-modal="true"
        aria-label="Add to golden set"
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="w-full max-w-lg space-y-3 rounded-lg bg-white p-5 shadow-xl"
      >
        <h2 className="text-lg font-semibold">Add to the golden set</h2>
        <p className="text-sm text-slate-600">“{item.question}”</p>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={answerable} onChange={(e) => setAnswerable(e.target.checked)} /> The documents contain the answer
        </label>
        {answerable && (
          <>
            <Field label="Expected answer">
              <input className={inputClass} value={expectedAnswer} onChange={(e) => setExpectedAnswer(e.target.value)} />
            </Field>
            <Field label="Source file name">
              <input className={inputClass} value={document} onChange={(e) => setDocument(e.target.value)} placeholder="parental-leave.md" required />
            </Field>
            <Field label="Exact quote from that file">
              <textarea className={inputClass} rows={2} value={quote} onChange={(e) => setQuote(e.target.value)} required />
            </Field>
          </>
        )}
        <Field label="Ask as group (optional)">
          <input className={inputClass} value={askAs} onChange={(e) => setAskAs(e.target.value)} placeholder="hr" />
        </Field>
        <Field label="Why is this being added?">
          <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} required />
        </Field>
        <ErrorBanner error={promote.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={promote.isPending}>
            Add
          </Button>
        </div>
      </form>
    </div>
  );
}
