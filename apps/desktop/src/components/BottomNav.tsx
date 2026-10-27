import { useTasks } from "../stores/tasks";
import type { Tab } from "../types";
import { IconArchive, IconDone, IconSettings, IconToday, IconUpcoming } from "./icons";

const TABS: { id: Tab; label: string; Icon: (p: { className?: string }) => React.JSX.Element }[] = [
  { id: "today", label: "Today", Icon: IconToday },
  { id: "upcoming", label: "Upcoming", Icon: IconUpcoming },
  { id: "completed", label: "Done", Icon: IconDone },
  { id: "archived", label: "Archived", Icon: IconArchive },
];

/** PRD §3.2-E navigation as a frosted bottom bar. Arrow keys move between tabs (WAI-ARIA tabs). */
export function BottomNav({ onSettings }: { onSettings: () => void }) {
  const tab = useTasks((s) => s.tab);
  const setTab = useTasks((s) => s.setTab);
  const todayCount = useTasks((s) => s.lists.today.length);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const i = TABS.findIndex((t) => t.id === tab);
    const next = TABS[(i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
    setTab(next.id);
    document.getElementById(`tab-${next.id}`)?.focus();
  };

  return (
    <nav aria-label="Panel" className="glass flex items-center gap-1 rounded-[22px] p-1.5">
      <div role="tablist" aria-label="Task views" onKeyDown={onKey} className="flex flex-1 gap-1">
        {TABS.map(({ id, label, Icon }) => {
          const selected = id === tab;
          return (
            <button
              key={id}
              id={`tab-${id}`}
              role="tab"
              type="button"
              aria-selected={selected}
              aria-controls="task-list"
              tabIndex={selected ? 0 : -1}
              onClick={() => setTab(id)}
              className={`relative flex flex-1 flex-col items-center gap-0.5 rounded-2xl py-1.5 text-[10.5px] font-semibold transition-colors ${
                selected ? "bg-card-hover text-fg" : "text-muted hover:text-fg"
              }`}
            >
              <span className="relative">
                <Icon className={`h-[18px] w-[18px] ${selected ? "text-accent" : ""}`} />
                {id === "today" && todayCount > 0 && (
                  <span className="absolute -right-2.5 -top-1.5 grid h-4 min-w-4 place-items-center rounded-full px-1 text-[9px] font-bold tabular-nums" style={{ background: "var(--z-cta)", color: "var(--z-cta-fg)" }}>
                    {todayCount}
                  </span>
                )}
              </span>
              {label}
            </button>
          );
        })}
      </div>
      <span aria-hidden className="h-7 w-px bg-line" />
      <button type="button" onClick={onSettings} aria-label="Settings" title="Settings" className="flex w-14 flex-col items-center gap-0.5 rounded-2xl py-1.5 text-[10.5px] font-semibold text-muted transition-colors hover:text-fg">
        <IconSettings className="h-[18px] w-[18px]" />
        Settings
      </button>
    </nav>
  );
}
