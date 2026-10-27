import { useState } from "react";
import { useTasks } from "../stores/tasks";
import { IconArrowUp, IconSliders, IconSparkle } from "./icons";

/**
 * One-line capture: type, Enter, done (PRD §1.2). Enter always saves the text as a task directly, so it
 * works with the AI offline; the sparkle button sends it to Ziko instead (same session and tools as voice).
 * Text survives closing the panel (the window is hidden, not destroyed).
 */
export function QuickAdd({ onOpenEditor }: { onOpenEditor: (title: string) => void }) {
  const [title, setTitle] = useState("");
  const create = useTasks((s) => s.create);
  const busy = useTasks((s) => Boolean(s.busy.new));
  const offline = useTasks((s) => s.backend !== "ready");
  const ask = useTasks((s) => s.ask);
  const [asking, setAsking] = useState(false);

  const askZiko = async () => {
    const t = title.trim();
    if (!t || asking) return;
    setAsking(true);
    if (await ask(t)) setTitle("");
    setAsking(false);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = title.trim();
    if (!t || busy) return;
    if (await create({ title: t })) setTitle(""); // keep text on failure so the user can retry
  };

  return (
    <form onSubmit={submit} className="glass flex items-center gap-1 rounded-full p-1.5 pl-4 focus-within:border-line-strong">
      <label htmlFor="quick-add" className="sr-only">Add a task</label>
      <input
        id="quick-add"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        maxLength={200}
        placeholder="Add a task, or ask Ziko…"
        disabled={offline}
        autoComplete="off"
        className="min-w-0 flex-1 bg-transparent py-1.5 text-sm text-fg outline-none placeholder:text-faint disabled:opacity-50"
      />
      <button type="button" onClick={() => void askZiko()} disabled={offline || !title.trim() || asking} className="icon-btn" aria-label="Ask Ziko" title="Ask Ziko (AI)">
        <IconSparkle />
      </button>
      <button type="button" onClick={() => onOpenEditor(title.trim())} disabled={offline} className="icon-btn" aria-label="Details" title="Add with date, reminder and priority">
        <IconSliders />
      </button>
      <button type="submit" disabled={offline || !title.trim() || busy} aria-label="Quick add" title="Add (Enter)" className="btn-cta !h-9 !w-9 !p-0">
        <IconArrowUp />
      </button>
    </form>
  );
}
