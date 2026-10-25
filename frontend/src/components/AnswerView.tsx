import type { Answer, Citation, EgressRecord } from "../api/client";
import { describeLocation, numberCitations } from "../lib/citations";
import { Badge } from "./ui";

interface Props {
  answer: Answer;
  onOpenSource: (citation: Citation) => void;
}

/** An answer where every sentence carries numbered citation chips. Clicking a chip opens the source viewer. */
export function AnswerView({ answer, onOpenSource }: Props) {
  return (
    <div className="space-y-3">
      {/* A server from before the public-research lane omits notices and egress: treat them as empty rather than crash. */}
      <Notices notices={answer.notices ?? []} />
      {answer.status === "refused" || answer.claims.length === 0 ? (
        <Refusal answer={answer} onOpenSource={onOpenSource} />
      ) : (
        <Claims answer={answer} onOpenSource={onOpenSource} />
      )}
      <EgressDisclosure egress={answer.egress ?? []} />
    </div>
  );
}

function Claims({ answer, onOpenSource }: Props) {
  const { claims, sources } = numberCitations(answer);
  const byNumber = new Map(sources.map((s) => [s.number, s.citation]));
  return (
    <div className="space-y-3">
      <p className="leading-7 text-slate-900">
        {claims.map((claim, i) => (
          <span key={i}>
            {claim.text}
            {claim.numbers.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => {
                  const citation = byNumber.get(n);
                  if (citation) onOpenSource(citation);
                }}
                aria-label={`Open source ${n}`}
                className={`mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded px-1 align-super text-[11px] font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                  byNumber.get(n)?.source_type === "public"
                    ? "bg-emerald-100 text-emerald-800 hover:bg-emerald-200"
                    : "bg-indigo-100 text-indigo-700 hover:bg-indigo-200"
                }`}
              >
                {n}
              </button>
            ))}{" "}
          </span>
        ))}
      </p>
      <ol className="space-y-1 border-t border-slate-100 pt-2 text-sm text-slate-600">
        {sources.map(({ number, citation }) => (
          <li key={number} className="flex gap-2">
            <span className="w-5 shrink-0 text-right font-semibold text-indigo-700">{number}</span>
            <span>
              {citation.source_type === "public" && (
                <span className="mr-1.5 rounded bg-emerald-100 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-emerald-800">
                  Public
                </span>
              )}
              <button type="button" className="text-left underline decoration-dotted hover:text-indigo-700" onClick={() => onOpenSource(citation)}>
                {describeLocation(citation)}
              </button>
              <span className="block text-slate-500">“{citation.quote}”</span>
            </span>
          </li>
        ))}
      </ol>
      <p className="text-xs text-slate-400">
        Every citation was checked against its source.
        {answer.dropped_claims > 0 && ` ${answer.dropped_claims} statement(s) were removed because the sources did not support them.`}
      </p>
    </div>
  );
}

function Notices({ notices }: { notices: string[] }) {
  if (notices.length === 0) return null;
  return (
    <ul role="status" className="space-y-1 rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-900" data-testid="notices">
      {notices.map((notice) => (
        <li key={notice}>{notice}</li>
      ))}
    </ul>
  );
}

/** Says plainly what left the system: which public sources received which keywords, or why nothing was sent. */
function EgressDisclosure({ egress }: { egress: EgressRecord[] }) {
  if (egress.length === 0) return null;
  const sent = egress.filter((r) => r.status === "sent");
  const blocked = egress.filter((r) => r.status === "blocked");
  const query = sent[0]?.query;
  return (
    <details className="text-xs text-slate-500" data-testid="egress">
      <summary className="cursor-pointer select-none">
        {sent.length > 0
          ? `Public search: keywords sent to ${sent.map((r) => r.destination).join(", ")}`
          : "Public search: nothing was sent"}
      </summary>
      <div className="mt-1 space-y-1 pl-3">
        {query && (
          <p>
            Only these keywords left the system: <code className="rounded bg-slate-100 px-1">{query}</code>. No document text was sent.
          </p>
        )}
        {blocked.map((r) => (
          <p key={r.destination}>Blocked before sending ({r.reason}).</p>
        ))}
        {egress
          .filter((r) => r.status === "failed")
          .map((r) => (
            <p key={r.destination}>{r.destination} did not respond.</p>
          ))}
      </div>
    </details>
  );
}

function Refusal({ answer, onOpenSource }: Props) {
  const refusal = answer.refusal;
  return (
    <div className="space-y-2 rounded-md border border-amber-200 bg-amber-50 p-3" data-testid="refusal">
      <p className="flex items-center gap-2 font-medium text-amber-900">
        <Badge value="refused" />
        {refusal?.message ?? "I don't have information on that."}
      </p>
      {refusal && refusal.closest_sources.length > 0 && (
        <div className="text-sm text-amber-900">
          <p className="mb-1">Closest documents you can read:</p>
          <ul className="list-inside list-disc">
            {refusal.closest_sources.map((s) => (
              <li key={s.chunk_id}>
                <button
                  type="button"
                  className="underline hover:text-amber-700"
                  onClick={() =>
                    onOpenSource({
                      chunk_id: s.chunk_id,
                      document_id: s.document_id,
                      document_title: s.document_title,
                      quote: "",
                      quote_start: 0,
                      quote_end: 0,
                      heading_path: [],
                      page_start: null,
                      page_end: null,
                    })
                  }
                >
                  {s.document_title}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
