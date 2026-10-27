import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { formatDue } from "../lib/time";
import { useTasks } from "../stores/tasks";
import type { Reminder } from "../types";
import { IconBell, IconClock } from "./icons";

/**
 * PRD §3.2-D "Upcoming reminders": reminders that fired and still need an answer (Snooze / Dismiss),
 * then the next scheduled one. Hidden when there is nothing to show, so it costs no space on quiet days.
 */
export function ReminderCard() {
  const reduce = useReducedMotion();
  const { attention, upcoming } = useTasks((s) => s.reminders);
  const tz = useTasks((s) => s.tz);
  const [next, ...later] = upcoming;
  if (!attention.length && !next) return null;

  return (
    <section aria-label="Reminders" className="glass flex flex-col gap-2 rounded-3xl px-3.5 py-3">
      <AnimatePresence initial={false}>
        {attention.map((r) => (
          <motion.div
            key={r.id}
            layout={!reduce}
            initial={reduce ? false : { opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduce ? undefined : { opacity: 0, height: 0 }}
          >
            <FiredReminder r={r} tz={tz} />
          </motion.div>
        ))}
      </AnimatePresence>

      {next && (
        <p className="flex min-w-0 items-center gap-2 text-xs font-medium text-muted">
          <IconClock className="h-3.5 w-3.5 shrink-0" />
          <span className="shrink-0">Next</span>
          <span className="truncate font-semibold text-fg">{next.task_title}</span>
          <time dateTime={next.fire_at} className="ml-auto shrink-0 tabular-nums">
            {formatDue(next.fire_at, tz)}
          </time>
          {later.length > 0 && <span className="shrink-0">+{later.length}</span>}
        </p>
      )}
    </section>
  );
}

function FiredReminder({ r, tz }: { r: Reminder; tz?: string }) {
  const busy = useTasks((s) => Boolean(s.busy[r.id]));
  const snooze = useTasks((s) => s.snooze);
  const dismiss = useTasks((s) => s.dismissReminder);

  return (
    <div role="alert" className={`flex items-center gap-2.5 ${busy ? "opacity-60" : ""}`} aria-busy={busy}>
      <span
        aria-hidden
        className={`grid h-8 w-8 shrink-0 place-items-center rounded-full ${r.missed ? "" : "animate-pulse"}`}
        style={{ background: r.missed ? "var(--z-danger)" : "var(--z-cta)", color: r.missed ? "#fff" : "var(--z-cta-fg)" }}
      >
        <IconBell className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-fg">{r.task_title}</p>
        <p className={`text-[11px] font-medium ${r.missed ? "text-danger" : "text-muted"}`}>
          {r.missed ? "Missed · " : "Reminder · "}
          <time dateTime={r.fire_at}>{formatDue(r.fire_at, tz)}</time>
        </p>
      </div>
      <button
        type="button"
        disabled={busy}
        onClick={() => void snooze(r.id)}
        className="chip glass glass-hover !border-0 px-2.5 py-1 text-fg"
        aria-label={`Snooze “${r.task_title}”`}
      >
        Snooze
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => void dismiss(r.id)}
        className="chip px-2.5 py-1 text-muted hover:text-fg"
        aria-label={`Dismiss “${r.task_title}”`}
      >
        Dismiss
      </button>
    </div>
  );
}
