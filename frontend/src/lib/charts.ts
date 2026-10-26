/** Pure helpers for the dashboard's hand-drawn SVG charts (no chart library, nothing loaded from a CDN). */

/** The smallest "round" number >= value (1, 2, 5 times a power of ten), so the y axis ends on a readable tick. */
export function niceMax(value: number): number {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 5, 10]) if (step * power >= value) return step * power;
  return 10 * power;
}

export function formatPercent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "n/a";
  const percent = rate * 100;
  return `${percent >= 10 || percent === 0 ? percent.toFixed(0) : percent.toFixed(1)}%`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "n/a";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

export function formatUsd(usd: number): string {
  if (usd === 0) return "$0";
  return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
}

export function formatCount(n: number): string {
  return n.toLocaleString("en-US");
}

/** "Oct 25" from an ISO date, without time-zone shifts (the server already counted days in UTC). */
export function shortDate(iso: string): string {
  const [year = 1970, month = 1, day = 1] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export interface DayBar {
  date: string;
  answered: number;
  refused: number;
}

export interface BarGeometry {
  x: number;
  width: number;
  answeredHeight: number;
  refusedHeight: number;
  total: number;
}

/** Column geometry in a plot of `width` x `height`: equal slots, bars 60% of a slot but never wider than `maxBar`. */
export function stackedBars(days: DayBar[], width: number, height: number, maxBar = 28): { bars: BarGeometry[]; top: number } {
  const top = niceMax(Math.max(0, ...days.map((d) => d.answered + d.refused)));
  const slot = days.length ? width / days.length : width;
  const barWidth = Math.min(maxBar, Math.max(2, slot * 0.6));
  const bars = days.map((d, i) => ({
    x: i * slot + (slot - barWidth) / 2,
    width: barWidth,
    answeredHeight: (d.answered / top) * height,
    refusedHeight: (d.refused / top) * height,
    total: d.answered + d.refused,
  }));
  return { bars, top };
}
