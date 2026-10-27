import { useEffect, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { emptyForm, formFromTask, REMINDER_OPTIONS, toCreate, toPatch, validate } from "../lib/editor";
import type { EditorForm } from "../lib/editor";
import { useTasks } from "../stores/tasks";
import type { Priority, Task } from "../types";
import { IconClose } from "./icons";

const PRIORITIES: Priority[] = ["low", "medium", "high"];

export type EditorTarget = { mode: "create"; title: string } | { mode: "edit"; task: Task };

/**
 * Add/edit form (PRD §3.2-C). Field order follows how people describe a task:
 * what → when → remind me → how important → notes.
 * While open, the panel ignores blur-to-close so a native date picker can't dismiss it.
 */
export function TaskEditor({ target, tz, onClose }: { target: EditorTarget; tz?: string; onClose: () => void }) {
  const reduce = useReducedMotion();
  const defaultPriority = "medium" as Priority;
  const initial = useMemo<EditorForm>(
    () => (target.mode === "edit" ? formFromTask(target.task, tz) : emptyForm(target.title, defaultPriority)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [target],
  );
  const [f, setF] = useState<EditorForm>(initial);
  const [error, setError] = useState<string | null>(null);
  const create = useTasks((s) => s.create);
  const update = useTasks((s) => s.update);
  const busy = useTasks((s) => Boolean(s.busy[target.mode === "edit" ? target.task.id : "new"]));
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => titleRef.current?.focus(), []);

  const set = <K extends keyof EditorForm>(k: K, v: EditorForm[K]) => {
    setF((prev) => ({ ...prev, [k]: v }));
    setError(null);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const problem = validate(f);
    if (problem) return setError(problem);
    let saved: Task | null;
    if (target.mode === "create") {
      saved = await create(toCreate(f));
    } else {
      const patch = toPatch(initial, f);
      if (Object.keys(patch).length === 0) return onClose();
      saved = await update(target.task.id, patch);
    }
    if (saved) return onClose();
    // Keep the form open with the user's input and show the backend's reason here, not behind the dialog.
    const { notice, dismissNotice } = useTasks.getState();
    if (notice?.kind === "error") {
      setError(notice.text);
      dismissNotice();
    }
  };

  const reminderOptions = REMINDER_OPTIONS.filter((o) => f.due || o.value === "none" || o.value === "custom");

  return (
    <motion.div
      className="sheet absolute inset-0 z-40 flex flex-col rounded-[28px] border border-line"
      initial={reduce ? false : { opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduce ? undefined : { opacity: 0, y: 24 }}
      transition={{ type: "spring", stiffness: 420, damping: 36 }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="editor-title"
    >
      <form onSubmit={submit} className="flex h-full flex-col gap-4 p-5" noValidate>
        <div className="flex items-center justify-between">
          <h2 id="editor-title" className="text-lg font-bold tracking-tight text-fg">
            {target.mode === "create" ? "New task" : "Edit task"}
          </h2>
          <button type="button" onClick={onClose} className="icon-btn" aria-label="Cancel">
            <IconClose />
          </button>
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="ed-title" className="label">Task</label>
          <input id="ed-title" ref={titleRef} className="field" maxLength={200} value={f.title} onChange={(e) => set("title", e.target.value)} placeholder="What needs doing?" required />
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="ed-due" className="label">Due</label>
          <div className="flex gap-2">
            <input id="ed-due" type="datetime-local" className="field flex-1" value={f.due} onChange={(e) => set("due", e.target.value)} />
            {f.due && (
              <button type="button" className="btn-ghost" onClick={() => setF((p) => ({ ...p, due: "", reminder: p.reminder === "custom" ? "custom" : "none" }))}>
                Clear
              </button>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="ed-reminder" className="label">Reminder</label>
          <select id="ed-reminder" className="field" value={f.reminder} onChange={(e) => set("reminder", e.target.value as EditorForm["reminder"])}>
            {reminderOptions.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {f.reminder === "custom" && (
            <input aria-label="Reminder time" type="datetime-local" className="field" value={f.reminderCustom} onChange={(e) => set("reminderCustom", e.target.value)} />
          )}
        </div>

        <fieldset className="flex flex-col gap-1.5">
          <legend className="label mb-1.5">Priority</legend>
          <div className="flex gap-1 rounded-full border border-line bg-field p-1">
            {PRIORITIES.map((p) => (
              <label key={p} className={`flex-1 cursor-pointer rounded-full px-2 py-1.5 text-center text-xs font-semibold capitalize transition-colors ${f.priority === p ? `chip-${p} shadow-sm` : "text-muted hover:text-fg"}`}>
                <input type="radio" name="priority" value={p} checked={f.priority === p} onChange={() => set("priority", p)} className="sr-only" />
                {p}
              </label>
            ))}
          </div>
        </fieldset>

        <div className="flex min-h-0 flex-1 flex-col gap-1.5">
          <label htmlFor="ed-notes" className="label">Notes <span className="font-normal text-faint">(optional)</span></label>
          <textarea id="ed-notes" className="field min-h-16 flex-1 resize-none !rounded-2xl" maxLength={4000} value={f.description} onChange={(e) => set("description", e.target.value)} />
        </div>

        <div aria-live="polite" className="min-h-4 text-xs font-medium text-danger">{error}</div>

        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-cta" disabled={busy}>
            {busy ? "Saving…" : target.mode === "create" ? "Add task" : "Save changes"}
          </button>
        </div>
      </form>
    </motion.div>
  );
}
