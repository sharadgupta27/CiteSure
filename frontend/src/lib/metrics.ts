import type { Schemas } from "../api/client";

export type MetricKey = Exclude<keyof Schemas["EvalMetrics"], "n_questions">;

export const METRIC_ORDER: MetricKey[] = [
  "recall_at_k",
  "mrr",
  "correctness",
  "faithfulness",
  "citation_precision",
  "citation_recall",
  "refusal_accuracy",
  "restricted_refusal_accuracy",
  "answerable_refusal_rate",
];

export const METRIC_LABELS: Record<MetricKey, string> = {
  recall_at_k: "Recall@k",
  mrr: "MRR",
  correctness: "Correct",
  faithfulness: "Faithful",
  citation_precision: "Cite prec.",
  citation_recall: "Cite recall",
  refusal_accuracy: "Refuses OK",
  restricted_refusal_accuracy: "Restricted",
  answerable_refusal_rate: "Wrongly refused",
};

/** For most metrics higher is better. "Wrongly refused" (answerable questions that were refused) is the exception. */
const LOWER_IS_BETTER = new Set<MetricKey>(["answerable_refusal_rate"]);

export function formatMetric(value: number | undefined): string {
  return value === undefined ? "–" : value.toFixed(2);
}

export function formatDelta(delta: number): string {
  if (Math.abs(delta) < 0.005) return "0.00";
  return `${delta > 0 ? "+" : "−"}${Math.abs(delta).toFixed(2)}`;
}

export function deltaClass(metric: MetricKey, delta: number): string {
  if (Math.abs(delta) < 0.005) return "text-slate-400";
  const improved = LOWER_IS_BETTER.has(metric) ? delta < 0 : delta > 0;
  return improved ? "text-emerald-600" : "text-red-600";
}
