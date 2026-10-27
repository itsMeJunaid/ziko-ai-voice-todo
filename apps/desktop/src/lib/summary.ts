import { dateKey, formatTime } from "./time";
import type { Task } from "../types";

export interface TodaySummary {
  pending: number;
  done: number;
  overdue: number;
  pct: number; // 0..100
  headline: string;
  detail: string;
}

/** Hero-card numbers, derived only from what the backend returned (never invented — PRD §5.1 Read). */
export function summarizeToday(today: Task[], completed: Task[], tz?: string, now = new Date()): TodaySummary {
  const key = dateKey(now, tz);
  const done = completed.filter((t) => t.completed_at && dateKey(new Date(t.completed_at), tz) === key).length;
  const pending = today.length;
  const overdue = today.filter((t) => t.is_overdue).length;
  const total = pending + done;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const next = today
    .filter((t) => t.due_at && !t.is_overdue)
    .map((t) => t.due_at!)
    .sort()[0];

  const headline =
    total === 0 ? "A clear day" : pending === 0 ? "All done for today" : `${pending} task${pending === 1 ? "" : "s"} left`;
  const parts: string[] = [];
  if (overdue) parts.push(`${overdue} overdue`);
  if (next) parts.push(`next at ${formatTime(next, tz)}`);
  if (!parts.length) parts.push(total === 0 ? "Add something to get started" : pending ? "No deadlines today" : "Nice work");
  const detail = parts.join(" · ");
  return { pending, done, overdue, pct, headline, detail: detail[0].toUpperCase() + detail.slice(1) };
}
