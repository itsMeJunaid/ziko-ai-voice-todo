import { AnimatePresence } from "framer-motion";
import { useTasks } from "../stores/tasks";
import type { Tab, Task } from "../types";
import { Pet } from "./Pet";
import { TaskCard } from "./TaskCard";

const META: Record<Tab, { title: string; empty: string; hint: string }> = {
  today: { title: "Today's tasks", empty: "Nothing due today", hint: "Add a task above, or enjoy the quiet." },
  upcoming: { title: "Upcoming", empty: "No upcoming tasks", hint: "Tasks due after today show up here." },
  completed: { title: "Completed", empty: "Nothing completed yet", hint: "Finished tasks stay here for 30 days." },
  archived: { title: "Archived", empty: "Archive is empty", hint: "Archived tasks can be restored from here." },
};

function Section({ label, tasks, tz, onEdit, tone }: { label?: string; tasks: Task[]; tz?: string; onEdit: (t: Task) => void; tone?: "danger" }) {
  if (!tasks.length) return null;
  return (
    <section aria-label={label} className="flex flex-col gap-2">
      {label && (
        <h3 className={`px-1 text-[11px] font-bold uppercase tracking-[0.14em] ${tone === "danger" ? "text-danger" : "text-muted"}`}>
          {label} <span className="tabular-nums opacity-70">{tasks.length}</span>
        </h3>
      )}
      <ul className="flex flex-col gap-2">
        <AnimatePresence initial={false}>
          {tasks.map((t) => (
            <TaskCard key={t.id} task={t} tz={tz} onEdit={onEdit} />
          ))}
        </AnimatePresence>
      </ul>
    </section>
  );
}

export function TaskList({ onEdit }: { onEdit: (t: Task) => void }) {
  const tab = useTasks((s) => s.tab);
  const tasks = useTasks((s) => s.lists[s.tab]);
  const loaded = useTasks((s) => s.loaded);
  const tz = useTasks((s) => s.tz);
  const meta = META[tab];

  let body: React.ReactNode;
  if (!loaded) {
    body = [0, 1, 2].map((i) => <div key={i} className="glass h-[68px] animate-pulse rounded-2xl" aria-hidden />);
  } else if (!tasks.length) {
    body = (
      <div className="glass flex flex-1 flex-col items-center justify-center gap-2 rounded-3xl px-6 py-10 text-center">
        <span aria-hidden className="h-14 w-14 opacity-90">
          <Pet size={56} asleep />
        </span>
        <p className="text-sm font-semibold text-fg">{meta.empty}</p>
        <p className="text-xs text-muted">{meta.hint}</p>
      </div>
    );
  } else if (tab === "today") {
    const overdue = tasks.filter((t) => t.is_overdue);
    const rest = tasks.filter((t) => !t.is_overdue);
    body = (
      <>
        <Section label="Overdue" tone="danger" tasks={overdue} tz={tz} onEdit={onEdit} />
        <Section label={overdue.length ? "Due today" : meta.title} tasks={rest} tz={tz} onEdit={onEdit} />
      </>
    );
  } else {
    body = <Section label={meta.title} tasks={tasks} tz={tz} onEdit={onEdit} />;
  }

  return (
    <div id="task-list" role="tabpanel" aria-labelledby={`tab-${tab}`} className="scroll-area fade-bottom -mx-1 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-1 pt-0.5 pb-6">
      {body}
    </div>
  );
}
