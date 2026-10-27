import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEvents } from "../hooks/useEvents";
import { useGlass } from "../lib/glass";
import { useTheme } from "../lib/theme";
import { getBackendInfo, isTauri, onBackendStatus } from "../services/backend";
import { hidePanel } from "../services/windows";
import { useTasks } from "../stores/tasks";
import type { BackendInfo, ServerEvent, Task } from "../types";
import { BottomNav } from "./BottomNav";
import { PanelHeader } from "./PanelHeader";
import { QuickAdd } from "./QuickAdd";
import { ReminderCard } from "./ReminderCard";
import { SettingsPanel } from "./SettingsPanel";
import { TaskEditor } from "./TaskEditor";
import type { EditorTarget } from "./TaskEditor";
import { TaskList } from "./TaskList";
import { TodayHero } from "./TodayHero";
import { VoiceBar } from "./VoiceBar";

const STATUS_TEXT: Record<string, string> = {
  starting: "Starting Ziko's local service…",
  down: "Local service stopped — restarting…",
  failed: "Ziko's local service could not start. Check the logs, then restart Ziko.",
};

/** The expanded glass task panel (PRD §3.2). Lives in its own always-on-top window. */
export function TaskPanel() {
  const reduce = useReducedMotion();
  const [info, setInfo] = useState<BackendInfo | null>(null);
  const [editor, setEditor] = useState<EditorTarget | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [theme, setTheme] = useTheme();
  const { pref: glassPref, setPref: setGlassPref, support } = useGlass(theme);
  const backend = useTasks((s) => s.backend);
  const tab = useTasks((s) => s.tab);
  const tz = useTasks((s) => s.tz);
  const notice = useTasks((s) => s.notice);
  const { connect, setBackendStatus, refresh, setEditorOpen, dismissNotice, onVoiceEvent } = useTasks.getState();

  // ---- backend discovery + lifecycle
  useEffect(() => {
    const apply = (i: BackendInfo) => {
      setInfo(i);
      if (i.status === "ready") void connect(i);
      else setBackendStatus(i.status);
    };
    void getBackendInfo().then(apply);
    const off = onBackendStatus(apply);
    return () => void off.then((u) => u());
  }, [connect, setBackendStatus]);

  // ---- live updates (voice / reminders / other windows change tasks too)
  const onEvent = useCallback(
    (e: ServerEvent) => {
      if (e.type === "task.changed" || e.type.startsWith("reminder.")) void refresh();
      else if (e.type.startsWith("voice.")) onVoiceEvent(e);
      else if (e.type === "settings.changed") {
        void useTasks.getState().applySettings();
        void useTasks.getState().recheckKey();
      }
    },
    [refresh, onVoiceEvent],
  );
  useEvents(info?.status === "ready" ? info.ws_url : null, onEvent);

  // ---- editor state is mirrored to the store so blur-to-close can respect it
  // Settings counts too: pasting a key means switching to the browser, which must not hide the panel.
  useEffect(() => setEditorOpen(editor !== null || settingsOpen), [editor, settingsOpen, setEditorOpen]);

  // ---- click outside closes the panel, unless an interaction must be completed (PRD §3.1)
  useEffect(() => {
    if (!isTauri()) return;
    let off: (() => void) | undefined;
    void (async () => {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      const { listen } = await import("@tauri-apps/api/event");
      const win = getCurrentWindow();
      const u1 = await win.onFocusChanged(({ payload: focused }) => {
        if (!focused && !useTasks.getState().editorOpen) void hidePanel("blur");
      });
      const u2 = await listen("ziko://add-task", () => setEditor({ mode: "create", title: "" }));
      const u3 = await listen("panel://shown", () => void refresh());
      off = () => [u1, u2, u3].forEach((u) => u());
    })();
    return () => off?.();
  }, [refresh]);

  // ---- keyboard: Esc closes the editor first, then the panel
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (useTasks.getState().editorOpen) {
        setEditor(null);
        setSettingsOpen(false);
      }
      else if (isTauri()) void hidePanel("user");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openEdit = useCallback((task: Task) => setEditor({ mode: "edit", task }), []);

  return (
    <div className="panel-frame">
      <motion.main
        className="shell flex h-full w-full flex-col gap-3.5 p-4 pb-3"
        initial={reduce ? false : { opacity: 0, scale: 0.97, y: 6 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 380, damping: 32 }}
        aria-label="Ziko tasks"
      >
        <div className="aurora" aria-hidden>
          <i />
          <i />
        </div>

        <PanelHeader tz={tz} onClose={() => void hidePanel("user")} />

        {backend !== "ready" && (
          <div role="status" className={`glass rounded-2xl px-3.5 py-2.5 text-xs font-medium ${backend === "failed" ? "text-danger" : "text-muted"}`}>
            {STATUS_TEXT[backend]}
          </div>
        )}

        {backend === "ready" && <VoiceBar onSetup={() => setSettingsOpen(true)} />}
        <QuickAdd onOpenEditor={(title) => setEditor({ mode: "create", title })} />
        {tab === "today" && <TodayHero />}
        <ReminderCard />
        <TaskList onEdit={openEdit} />
        <BottomNav onSettings={() => setSettingsOpen(true)} />

        <div aria-live="polite" className="pointer-events-none absolute inset-x-4 bottom-[84px] z-30 flex justify-center">
          <AnimatePresence>
            {notice && (
              <motion.button
                key={notice.id}
                type="button"
                onClick={dismissNotice}
                initial={reduce ? false : { opacity: 0, y: 8, scale: 0.96 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={reduce ? undefined : { opacity: 0, y: 8 }}
                className={`sheet pointer-events-auto rounded-full border px-4 py-2 text-xs font-semibold shadow-lg ${notice.kind === "error" ? "border-danger/40 text-danger" : "border-line text-fg"}`}
              >
                {notice.kind === "ok" ? "✓ " : ""}
                {notice.text}
              </motion.button>
            )}
          </AnimatePresence>
        </div>

        <AnimatePresence>
          {settingsOpen && (
            <SettingsPanel
              key="settings"
              onClose={() => setSettingsOpen(false)}
              theme={theme}
              onTheme={setTheme}
              glassPref={glassPref}
              onGlass={setGlassPref}
              glassSupport={support}
            />
          )}
          {editor && <TaskEditor key={editor.mode === "edit" ? editor.task.id : "new"} target={editor} tz={tz} onClose={() => setEditor(null)} />}
        </AnimatePresence>
      </motion.main>
    </div>
  );
}
