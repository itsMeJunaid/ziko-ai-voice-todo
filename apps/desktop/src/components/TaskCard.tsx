import { motion, useReducedMotion } from "framer-motion";
import { formatDue } from "../lib/time";
import { useTasks } from "../stores/tasks";
import type { Task } from "../types";
import { IconArchive, IconBell, IconCheck, IconClock, IconEdit, IconRestore } from "./icons";

const PRIORITY: Record<Task["priority"], { label: string; chip: string }> = {
  high: { label: "High", chip: "chip-high" },
  medium: { label: "Medium", chip: "chip-medium" },
  low: { label: "Low", chip: "chip-low" },
};

/**
 * PRD §3.2-C task card: round completion check, title, priority chip, due, reminder, edit, archive.
 * State is always carried by text as well as colour (PRD §10.5).
 */
export function TaskCard({ task, tz, onEdit }: { task: Task; tz?: string; onEdit: (t: Task) => void }) {
  const reduce = useReducedMotion();
  const busy = useTasks((s) => Boolean(s.busy[task.id]));
  const toggleComplete = useTasks((s) => s.toggleComplete);
  const archive = useTasks((s) => s.archive);
  const restore = useTasks((s) => s.restore);
  const done = task.status === "completed";
  const archived = task.status === "archived";
  const p = PRIORITY[task.priority];

  return (
    <motion.li
      layout={!reduce}
      initial={reduce ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduce ? undefined : { opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.18 }}
      className={`glass glass-hover group flex items-start gap-3 rounded-2xl px-3.5 py-3 ${busy ? "opacity-60" : ""}`}
      aria-busy={busy}
    >
      {!archived && (
        <button
          type="button"
          role="checkbox"
          aria-checked={done}
          aria-label={done ? `Mark “${task.title}” as not done` : `Mark “${task.title}” as done`}
          disabled={busy}
          onClick={() => void toggleComplete(task)}
          className={`mt-0.5 grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full border-2 transition-all ${
            done ? "border-transparent" : "border-line-strong hover:border-accent hover:scale-105"
          }`}
          style={done ? { background: "var(--z-cta)", color: "var(--z-cta-fg)" } : undefined}
        >
          {done && <IconCheck className="h-3 w-3" />}
        </button>
      )}

      <div className="min-w-0 flex-1">
        <p className={`text-sm font-semibold leading-snug break-words ${done || archived ? "text-muted line-through decoration-1" : "text-fg"}`}>
          {task.title}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] font-medium text-muted">
          <span className={`chip ${p.chip}`}>{p.label}<span className="sr-only"> priority</span></span>
          {task.due_at && (
            <span className={`inline-flex items-center gap-1 ${task.is_overdue ? "font-semibold text-danger" : ""}`}>
              <IconClock className="h-3 w-3" />
              {task.is_overdue && <span>Overdue ·</span>}
              <span className="sr-only">{task.is_overdue ? "was due" : "due"}</span>
              <time dateTime={task.due_at}>{formatDue(task.due_at, tz)}</time>
            </span>
          )}
          {task.reminder_at && !done && !archived && (
            <span className="inline-flex items-center gap-1">
              <IconBell className="h-3 w-3" />
              <span className="sr-only">Reminder</span>
              <time dateTime={task.reminder_at}>{formatDue(task.reminder_at, tz)}</time>
            </span>
          )}
        </div>
      </div>

      <div className="-mr-1 -mt-1 flex shrink-0 items-center opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100">
        {archived ? (
          <button type="button" className="icon-btn" disabled={busy} onClick={() => void restore(task.id)} aria-label={`Restore “${task.title}”`} title="Restore">
            <IconRestore />
          </button>
        ) : (
          <>
            <button type="button" className="icon-btn" disabled={busy} onClick={() => onEdit(task)} aria-label={`Edit “${task.title}”`} title="Edit">
              <IconEdit />
            </button>
            <button type="button" className="icon-btn" disabled={busy} onClick={() => void archive(task.id)} aria-label={`Archive “${task.title}”`} title="Archive (recoverable)">
              <IconArchive />
            </button>
          </>
        )}
      </div>
    </motion.li>
  );
}
