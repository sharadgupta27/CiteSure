import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Citation } from "../../api/client";
import { useDeletePlan, useLearningPlan, useSetPlanStepDone, type PlanStep } from "../../api/hooksLearning";
import { AnswerView } from "../AnswerView";
import { SourceViewer } from "../SourceViewer";
import { Button, Card, ErrorBanner, Spinner } from "../ui";
import { ProgressBar, formatMinutes } from "./ProgressBar";

function pagesLabel(step: PlanStep): string | null {
  if (step.page_start == null) return null;
  return step.page_end != null && step.page_end !== step.page_start ? `pp. ${step.page_start}-${step.page_end}` : `p. ${step.page_start}`;
}

function StepCard({
  step,
  busy,
  onToggle,
  onOpenSource,
}: {
  step: PlanStep;
  busy: boolean;
  onToggle: (done: boolean) => void;
  onOpenSource: (citation: Citation) => void;
}) {
  const where = [step.label, pagesLabel(step)].filter(Boolean).join(" - ");
  return (
    <li className={`rounded-2xl border bg-white p-4 shadow-soft ${step.done ? "border-emerald-200" : "border-slate-200/80"}`}>
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          className="mt-1.5 h-4 w-4"
          aria-label={`Mark step ${step.position} done: ${step.document_title}`}
          checked={step.done}
          disabled={busy}
          onChange={(e) => onToggle(e.target.checked)}
        />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className={`font-semibold ${step.done ? "text-slate-500 line-through" : "text-slate-900"}`}>
              {step.position}. {step.document_title}
            </h3>
            <span className="text-xs text-slate-500">{formatMinutes(step.est_minutes)}</span>
          </div>
          {where && <p className="text-sm text-slate-600">{where}</p>}
          <ProgressBar percent={step.reading_percent} label={`Reading progress in ${step.document_title}`} />
          <div className="rounded-xl bg-slate-50 p-3 text-sm">
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">What you will learn</p>
            {step.objective ? (
              <AnswerView answer={step.objective} onOpenSource={onOpenSource} />
            ) : (
              <p className="text-slate-500">No objective was generated for this step.</p>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}

/** A plan with overall progress, steps grouped by week, and each step's verified objective. */
export function PlanView({ planId, workspaceId }: { planId: string; workspaceId: string }) {
  const plan = useLearningPlan(planId);
  const toggle = useSetPlanStepDone(planId);
  const remove = useDeletePlan(workspaceId);
  const navigate = useNavigate();
  const [source, setSource] = useState<Citation | null>(null);

  if (plan.isLoading) return <Spinner label="Loading plan" />;
  if (plan.error || !plan.data) return <ErrorBanner error={plan.error ?? new Error("Plan not found")} />;
  const data = plan.data;
  const weeks = [...new Set(data.steps.map((s) => s.week))].sort((a, b) => a - b);

  return (
    <div className="space-y-4">
      <Link to="/learn" className="text-sm text-indigo-700 hover:underline">
        Back to Learn
      </Link>
      <Card
        title={data.title}
        actions={
          <Button
            variant="danger"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(`Delete the plan "${data.title}"?`)) remove.mutate(data.id, { onSuccess: () => navigate("/learn") });
            }}
          >
            Delete
          </Button>
        }
      >
        {data.topic && <p className="mb-1 text-sm text-slate-600">Topic: {data.topic}</p>}
        <p className="mb-1 text-sm text-slate-600">
          {data.steps_done} of {data.steps_total} steps done ({Math.round(data.percent)}%) - about {formatMinutes(data.total_minutes)} over {data.weeks} week
          {data.weeks === 1 ? "" : "s"} at {data.hours_per_week} h/week
        </p>
        <ProgressBar percent={data.percent} label="Plan progress" />
        <div className="mt-2 space-y-2">
          <ErrorBanner error={toggle.error} />
          <ErrorBanner error={remove.error} />
        </div>
      </Card>

      {data.steps.length === 0 && <p className="text-sm text-slate-500">None of this plan's documents are readable by you any more.</p>}
      {weeks.map((week) => (
        <section key={week} aria-label={`Week ${week}`} className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Week {week}</h2>
          <ul className="space-y-3">
            {data.steps
              .filter((s) => s.week === week)
              .map((step) => (
                <StepCard
                  key={step.id}
                  step={step}
                  busy={toggle.isPending}
                  onToggle={(done) => toggle.mutate({ stepId: step.id, done })}
                  onOpenSource={setSource}
                />
              ))}
          </ul>
        </section>
      ))}
      <SourceViewer citation={source} onClose={() => setSource(null)} />
    </div>
  );
}
