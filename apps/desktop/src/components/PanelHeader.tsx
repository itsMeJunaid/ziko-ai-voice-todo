import { useClock } from "../hooks/useClock";
import { formatClock, formatHeaderDate, greeting } from "../lib/time";
import { IconClose } from "./icons";
import { Pet } from "./Pet";

/** PRD §3.2-A: identity, greeting, date, live clock, close. Theme and glass live in Settings. */
export function PanelHeader({ tz, onClose }: { tz?: string; onClose: () => void }) {
  const now = useClock();
  return (
    <header className="flex items-start justify-between gap-3" data-tauri-drag-region>
      <div className="flex min-w-0 items-center gap-3" data-tauri-drag-region>
        <span aria-hidden className="pointer-events-none h-10 w-10 shrink-0">
          <Pet size={40} />
        </span>
        <div className="min-w-0" data-tauri-drag-region>
          <p className="truncate text-[22px] font-bold leading-tight tracking-tight text-fg">{greeting(now, tz)}</p>
          <p className="mt-0.5 truncate whitespace-nowrap text-xs font-medium text-muted">
            {formatHeaderDate(now, tz)} ·{" "}
            <time dateTime={now.toISOString()} className="tabular-nums">{formatClock(now, tz)}</time>
          </p>
        </div>
      </div>
      <button type="button" onClick={onClose} aria-label="Close panel" title="Close (Esc)" className="icon-btn -mr-1">
        <IconClose />
      </button>
    </header>
  );
}
