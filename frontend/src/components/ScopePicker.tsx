import { useState } from "react";
import type { AskScope, PublicQueryPreview, PublicResearchStatus } from "../api/client";
import { usePreviewPublicQuery } from "../api/hooks";
import { Button, ErrorBanner, inputClass } from "./ui";

interface Props {
  status: PublicResearchStatus;
  scope: AskScope;
  onScope: (scope: AskScope) => void;
  question: string;
  /** The query the user approved or edited. null = let the server derive keywords from the question. */
  publicQuery: string | null;
  onPublicQuery: (query: string | null) => void;
}

const OPTIONS: { value: AskScope; label: string; hint: string }[] = [
  { value: "internal", label: "Company documents", hint: "Nothing leaves the system." },
  { value: "public", label: "Published research", hint: "Papers and web pages only. Your documents are not used." },
  { value: "both", label: "Both", hint: "Your documents plus published research, answered on this system." },
];

/** Chooses where an answer may draw from, and lets the user see (and edit) exactly what would leave before it does. */
export function ScopePicker({ status, scope, onScope, question, publicQuery, onPublicQuery }: Props) {
  const preview = usePreviewPublicQuery();
  const [shown, setShown] = useState<{ question: string; result: PublicQueryPreview } | null>(null);
  const current = shown && shown.question === question.trim() ? shown.result : null;
  const usesPublic = scope !== "internal";

  async function check(query: string | null) {
    const trimmed = question.trim();
    const result = await preview.mutateAsync({ question: trimmed, query });
    setShown({ question: trimmed, result });
    onPublicQuery(result.allowed ? result.query : query);
  }

  return (
    <fieldset className="space-y-2 rounded-md border border-slate-200 bg-white p-3" data-testid="scope-picker">
      <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Where to look</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {OPTIONS.map((option) => (
          <label key={option.value} className="flex cursor-pointer items-center gap-1.5 text-sm text-slate-700">
            <input
              type="radio"
              name="scope"
              value={option.value}
              checked={scope === option.value}
              onChange={() => {
                onScope(option.value);
                onPublicQuery(null);
                setShown(null);
              }}
            />
            {option.label}
          </label>
        ))}
      </div>
      <p className="text-xs text-slate-500">
        {OPTIONS.find((o) => o.value === scope)?.hint}
        {status.private_mode && " Private mode: company text is read only by the model running on this system."}
      </p>

      {usesPublic && (
        <div className="space-y-2 border-t border-slate-100 pt-2">
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="secondary" disabled={question.trim().length < 3 || preview.isPending} onClick={() => void check(publicQuery)}>
              Preview what will be sent
            </Button>
            <span className="text-xs text-slate-500">Only keywords go to {status.sources.join(", ")}. Never document text.</span>
          </div>
          <ErrorBanner error={preview.error} />
          {current && (
            <div className="space-y-1" data-testid="preview">
              <label className="block text-xs font-medium text-slate-600" htmlFor="public-query">
                Public search keywords (you can edit them)
              </label>
              <div className="flex gap-2">
                <input
                  id="public-query"
                  className={inputClass}
                  value={publicQuery ?? current.query}
                  maxLength={300}
                  onChange={(e) => onPublicQuery(e.target.value)}
                />
                <Button type="button" variant="secondary" onClick={() => void check(publicQuery ?? current.query)}>
                  Check
                </Button>
              </div>
              {current.allowed ? (
                <p className="text-xs text-emerald-700">Allowed: nothing sensitive was found in these keywords.</p>
              ) : (
                <p role="alert" className="text-xs text-red-700">
                  Blocked: {current.explanation || "the egress check did not pass"}. Edit the keywords, or ask about company documents only.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </fieldset>
  );
}
