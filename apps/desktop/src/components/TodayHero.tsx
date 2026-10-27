import { useMemo } from "react";
import { summarizeToday } from "../lib/summary";
import { useTasks } from "../stores/tasks";

function Ring({ pct }: { pct: number }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 64 64" className="h-16 w-16 -rotate-90" aria-hidden>
      <circle cx="32" cy="32" r={r} fill="none" stroke="var(--z-track)" strokeWidth="7" />
      <circle
        cx="32" cy="32" r={r} fill="none" stroke="var(--z-fg)" strokeWidth="7" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)}
        style={{ transition: "stroke-dashoffset 500ms ease" }}
      />
    </svg>
  );
}

/** Today at a glance: progress ring + what's left, overdue and next deadline (PRD §6.1). */
export function TodayHero() {
  const today = useTasks((s) => s.lists.today);
  const completed = useTasks((s) => s.lists.completed);
  const tz = useTasks((s) => s.tz);
  const loaded = useTasks((s) => s.loaded);
  const s = useMemo(() => summarizeToday(today, completed, tz), [today, completed, tz]);

  if (!loaded) return <div className="glass h-[92px] animate-pulse rounded-3xl" aria-hidden />;

  return (
    <section aria-label="Today at a glance" className="glass relative flex items-center gap-4 overflow-clip rounded-3xl px-4 py-3.5">
      <div className="relative grid place-items-center">
        <Ring pct={s.pct} />
        <span className="absolute text-sm font-bold tabular-nums text-fg">{s.pct}%</span>
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">Today</p>
        <p className="truncate text-lg font-bold leading-snug text-fg">{s.headline}</p>
        <p className={`truncate text-xs font-medium ${s.overdue ? "text-danger" : "text-muted"}`}>{s.detail}</p>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1 text-[11px] font-semibold">
        <span className="chip glass !border-0 text-fg tabular-nums">{s.done} done</span>
        {s.overdue > 0 && <span className="chip chip-high tabular-nums">{s.overdue} overdue</span>}
      </div>
    </section>
  );
}
