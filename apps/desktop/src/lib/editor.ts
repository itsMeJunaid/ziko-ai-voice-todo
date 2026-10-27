/**
 * Pure form logic for the task editor, kept out of the component so it is unit-testable.
 * All times are naive wall-time strings in the user's zone ("YYYY-MM-DDTHH:mm").
 */
import { shiftWallTime, toInputValue, wallDiffMinutes } from "./time";
import type { Priority, Task, TaskCreate, TaskPatch } from "../types";

export const REMINDER_OPTIONS = [
  { value: "none", label: "No reminder" },
  { value: "0", label: "At due time" },
  { value: "5", label: "5 minutes before" },
  { value: "15", label: "15 minutes before" },
  { value: "30", label: "30 minutes before" },
  { value: "60", label: "1 hour before" },
  { value: "1440", label: "1 day before" },
  { value: "custom", label: "Custom time…" },
] as const;
export type ReminderChoice = (typeof REMINDER_OPTIONS)[number]["value"];

export interface EditorForm {
  title: string;
  description: string;
  priority: Priority;
  due: string; // "" = no deadline
  reminder: ReminderChoice;
  reminderCustom: string;
}

export function emptyForm(title = "", priority: Priority = "medium"): EditorForm {
  return { title, description: "", priority, due: "", reminder: "none", reminderCustom: "" };
}

export function formFromTask(t: Task, tz?: string): EditorForm {
  const due = toInputValue(t.due_at, tz);
  const rem = toInputValue(t.reminder_at, tz);
  let reminder: ReminderChoice = "none";
  let reminderCustom = "";
  if (rem) {
    const offset = due ? wallDiffMinutes(rem, due) : NaN;
    const preset = REMINDER_OPTIONS.find((o) => o.value === String(offset));
    if (preset) reminder = preset.value;
    else {
      reminder = "custom";
      reminderCustom = rem;
    }
  }
  return { title: t.title, description: t.description ?? "", priority: t.priority, due, reminder, reminderCustom };
}

/** Resolved reminder wall time, or null. Offsets need a deadline; without one only "custom" applies. */
export function reminderValue(f: EditorForm): string | null {
  if (f.reminder === "none") return null;
  if (f.reminder === "custom") return f.reminderCustom || null;
  return f.due ? shiftWallTime(f.due, -Number(f.reminder)) : null;
}

/** Client-side checks mirror the backend's so the user gets instant feedback; the backend stays authoritative. */
export function validate(f: EditorForm): string | null {
  if (!f.title.trim()) return "Give the task a title";
  if (f.reminder === "custom" && !f.reminderCustom) return "Pick a reminder time";
  if (f.reminder !== "none" && f.reminder !== "custom" && !f.due) return "Set a due time for a relative reminder";
  const r = reminderValue(f);
  if (r && f.due && r > f.due) return "The reminder can't be after the due time";
  return null;
}

export function toCreate(f: EditorForm): TaskCreate {
  return {
    title: f.title.trim(),
    description: f.description.trim() || null,
    priority: f.priority,
    due_at: f.due || null,
    reminder_at: reminderValue(f),
  };
}

/** Only changed fields: an untouched past reminder must not be re-sent (the backend would reject it). */
export function toPatch(initial: EditorForm, f: EditorForm): TaskPatch {
  const patch: TaskPatch = {};
  if (f.title.trim() !== initial.title) patch.title = f.title.trim();
  if (f.description.trim() !== initial.description) patch.description = f.description.trim() || null;
  if (f.priority !== initial.priority) patch.priority = f.priority;
  if (f.due !== initial.due) patch.due_at = f.due || null;
  const before = reminderValue(initial);
  const after = reminderValue(f);
  if (after !== before) patch.reminder_at = after;
  return patch;
}
