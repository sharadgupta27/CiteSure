/**
 * Small charts drawn as inline SVG. No chart library and nothing fetched from a CDN (private deployments load
 * nothing from third parties). Colours are CSS variables on `.viz` with their own surface, so a chart is readable on
 * a light or a dark system theme; every chart has a table view and a text summary for screen readers, and identity is
 * never carried by colour alone (legend + labels).
 */
import { useState, type ReactNode } from "react";
import { formatCount, shortDate, stackedBars, type DayBar } from "../lib/charts";

const VIZ_CSS = `
.viz { color-scheme: light; --surface:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e; --grid:#e4e3df; --s1:#2a78d6; --s2:#eb6834;
  background: var(--surface); color: var(--ink); border-radius: 0.75rem; }
@media (prefers-color-scheme: dark) { .viz { color-scheme: dark; --surface:#1a1a19; --ink:#f0efec; --ink-2:#c3c2b7; --grid:#3a3a37; --s1:#3987e5; --s2:#d95926; } }
.viz svg text { fill: var(--ink-2); font-size: 11px; }
.viz .bar-1 { fill: var(--s1); } .viz .bar-2 { fill: var(--s2); }
.viz table { border-collapse: collapse; } .viz th, .viz td { padding: 0.25rem 0.75rem; text-align: right; border-bottom: 1px solid var(--grid); }
.viz th:first-child, .viz td:first-child { text-align: left; }
`;

export function VizStyles() {
  return <style>{VIZ_CSS}</style>;
}

export function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-white p-4 shadow-soft">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-3xl font-bold tabular-nums text-slate-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

function ChartFrame({ title, summary, table, children, legend }: { title: string; summary: string; table: ReactNode; children: ReactNode; legend?: ReactNode }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <figure className="viz p-4">
      <figcaption className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold">{title}</span>
        <button
          type="button"
          className="rounded-lg border border-slate-300 px-2 py-0.5 text-xs font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          style={{ color: "var(--ink)" }}
          aria-pressed={asTable}
          onClick={() => setAsTable((v) => !v)}
        >
          {asTable ? "Show chart" : "Show as table"}
        </button>
      </figcaption>
      <p className="sr-only">{summary}</p>
      {legend && <div className="mb-2 flex flex-wrap gap-4 text-xs">{legend}</div>}
      {asTable ? <div className="overflow-x-auto text-xs">{table}</div> : children}
    </figure>
  );
}

function Swatch({ cls, label }: { cls: "bar-1" | "bar-2"; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5" style={{ color: "var(--ink-2)" }}>
      <svg width="10" height="10" aria-hidden="true">
        <rect width="10" height="10" rx="2" className={cls} />
      </svg>
      {label}
    </span>
  );
}

const W = 640;
const H = 180;
const PAD = { left: 34, right: 8, top: 8, bottom: 22 };

/** Questions per day, stacked: answered (blue) below refused (orange). */
export function DayBarChart({ days }: { days: (DayBar & { questions: number; cost_usd: number })[] }) {
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const { bars, top } = stackedBars(days, plotW, plotH);
  const total = days.reduce((n, d) => n + d.questions, 0);
  const ticks = [0, top / 2, top];
  const labelEvery = Math.max(1, Math.ceil(days.length / 8));
  return (
    <ChartFrame
      title="Questions per day"
      summary={`${formatCount(total)} questions over ${days.length} days, split into answered and refused.`}
      legend={
        <>
          <Swatch cls="bar-1" label="Answered" />
          <Swatch cls="bar-2" label="Refused" />
        </>
      }
      table={
        <table>
          <thead>
            <tr>
              <th scope="col">Day</th>
              <th scope="col">Answered</th>
              <th scope="col">Refused</th>
              <th scope="col">Total</th>
            </tr>
          </thead>
          <tbody>
            {days.map((d) => (
              <tr key={d.date}>
                <th scope="row" className="font-normal">{shortDate(d.date)}</th>
                <td>{d.answered}</td>
                <td>{d.refused}</td>
                <td>{d.questions}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Questions per day, ${formatCount(total)} in total`}>
        <g transform={`translate(${PAD.left} ${PAD.top})`}>
          {ticks.map((t) => {
            const y = plotH - (t / top) * plotH;
            return (
              <g key={t}>
                <line x1={0} x2={plotW} y1={y} y2={y} stroke="var(--grid)" strokeWidth={1} />
                <text x={-6} y={y + 4} textAnchor="end">{Number.isInteger(t) ? t : t.toFixed(1)}</text>
              </g>
            );
          })}
          {days.map((day, i) => {
            const bar = bars[i];
            if (!bar) return null;
            const base = plotH;
            const gap = bar.answeredHeight > 0 && bar.refusedHeight > 0 ? 2 : 0; // a surface-coloured gap between segments
            return (
              <g key={day.date}>
                <title>{`${shortDate(day.date)}: ${day.answered} answered, ${day.refused} refused`}</title>
                {bar.answeredHeight > 0 && (
                  <rect className="bar-1" x={bar.x} y={base - bar.answeredHeight} width={bar.width} height={bar.answeredHeight} rx={bar.refusedHeight > 0 ? 0 : 3} />
                )}
                {bar.refusedHeight > 0 && (
                  <rect className="bar-2" x={bar.x} y={base - bar.answeredHeight - bar.refusedHeight - gap} width={bar.width} height={bar.refusedHeight} rx={3} />
                )}
                {i % labelEvery === 0 && (
                  <text x={bar.x + bar.width / 2} y={plotH + 15} textAnchor="middle">{shortDate(day.date)}</text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
    </ChartFrame>
  );
}

export interface HBarRow {
  label: string;
  value: number;
}

/** A ranked list of counts as horizontal bars with the number printed at the end of each. */
export function HBars({ title, rows, unit, empty }: { title: string; rows: HBarRow[]; unit: string; empty: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  const rowH = 26;
  const labelW = 150;
  const height = Math.max(rowH, rows.length * rowH);
  return (
    <ChartFrame
      title={title}
      summary={rows.length ? rows.map((r) => `${r.label}: ${r.value}`).join(", ") : `${title}: none`}
      table={
        <table>
          <thead>
            <tr>
              <th scope="col">Item</th>
              <th scope="col">{unit}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label}>
                <th scope="row" className="font-normal">{r.label}</th>
                <td>{r.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {rows.length === 0 ? (
        <p className="py-4 text-sm" style={{ color: "var(--ink-2)" }}>{empty}</p>
      ) : (
        <svg viewBox={`0 0 ${W} ${height}`} className="w-full" role="img" aria-label={title}>
          {rows.map((r, i) => {
            const barW = ((W - labelW - 60) * r.value) / max;
            return (
              <g key={r.label} transform={`translate(0 ${i * rowH})`}>
                <title>{`${r.label}: ${r.value} ${unit.toLowerCase()}`}</title>
                <text x={labelW - 8} y={rowH / 2 + 4} textAnchor="end">{r.label.length > 24 ? `${r.label.slice(0, 23)}…` : r.label}</text>
                <rect className="bar-1" x={labelW} y={5} width={Math.max(2, barW)} height={rowH - 12} rx={3} />
                <text x={labelW + Math.max(2, barW) + 6} y={rowH / 2 + 4} style={{ fill: "var(--ink)" }}>{formatCount(r.value)}</text>
              </g>
            );
          })}
        </svg>
      )}
    </ChartFrame>
  );
}
