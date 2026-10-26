/** A thin accessible progress bar. `percent` is 0-100; `label` names what is measured for screen readers. */
export function ProgressBar({ percent, label, className = "" }: { percent: number; label: string; className?: string }) {
  const value = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      className={`h-2 w-full overflow-hidden rounded-full bg-slate-100 ${className}`}
    >
      <div className={`h-full rounded-full transition-all ${value >= 100 ? "bg-emerald-500" : "bg-indigo-500"}`} style={{ width: `${value}%` }} />
    </div>
  );
}

/** "45 min", "1 h 15 min" */
export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}
