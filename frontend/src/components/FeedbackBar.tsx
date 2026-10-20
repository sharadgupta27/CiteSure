import { useState } from "react";
import { useSendFeedback } from "../api/hooks";
import { Button, ErrorBanner, inputClass } from "./ui";

/** Thumbs up / down with an optional comment. A thumbs-down lands in the admin's feedback queue. */
export function FeedbackBar({ answerId }: { answerId: string }) {
  const send = useSendFeedback();
  const [rating, setRating] = useState<-1 | 1 | null>(null);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);

  if (sent) return <p className="text-sm text-emerald-700">Thanks, your feedback was saved.</p>;

  async function submit(value: -1 | 1, text: string | null) {
    await send.mutateAsync({ answerId, rating: value, comment: text });
    setSent(true);
  }

  return (
    <div className="space-y-2 text-sm">
      <div className="flex items-center gap-2 text-slate-500">
        <span>Was this helpful?</span>
        <Button variant="secondary" aria-label="Thumbs up" disabled={send.isPending} onClick={() => void submit(1, null)}>
          👍
        </Button>
        <Button variant="secondary" aria-label="Thumbs down" disabled={send.isPending} onClick={() => setRating(-1)}>
          👎
        </Button>
      </div>
      {rating === -1 && (
        <div className="space-y-2">
          <textarea
            className={inputClass}
            rows={2}
            placeholder="What was wrong or missing? (optional)"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            aria-label="Feedback comment"
          />
          <Button disabled={send.isPending} onClick={() => void submit(-1, comment.trim() || null)}>
            Send feedback
          </Button>
        </div>
      )}
      <ErrorBanner error={send.error} />
    </div>
  );
}
