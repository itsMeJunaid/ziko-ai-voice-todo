import { create } from "zustand";
import { Api, ApiError } from "../services/api";
import { applyAppearance } from "../lib/appearance";
import { addTranscript } from "../lib/voice";
import type { BackendInfo, BackendStatus, ReminderList, ServerEvent, Tab, Task, TaskCreate, TaskPatch, TranscriptLine, VoiceStatus } from "../types";

const TABS: Tab[] = ["today", "upcoming", "completed", "archived"];

export interface Notice {
  kind: "ok" | "error";
  text: string;
  id: number;
}

interface TaskState {
  api: Api | null;
  backend: BackendStatus;
  tz: string | undefined;
  tab: Tab;
  lists: Record<Tab, Task[]>;
  reminders: ReminderList;
  loaded: boolean;
  /** ids with a request in flight ("new" for create) — blocks duplicate submissions (PRD §3.2). */
  busy: Record<string, true>;
  notice: Notice | null;
  editorOpen: boolean;
  voice: VoiceStatus | null;
  transcript: TranscriptLine[];
  /** null until known. */
  hasKey: boolean | null;

  connect(info: BackendInfo): Promise<void>;
  setBackendStatus(s: BackendStatus): void;
  setTab(t: Tab): void;
  setEditorOpen(open: boolean): void;
  refresh(): Promise<void>;
  create(body: TaskCreate): Promise<Task | null>;
  update(id: string, patch: TaskPatch): Promise<Task | null>;
  toggleComplete(task: Task): Promise<void>;
  archive(id: string): Promise<void>;
  restore(id: string): Promise<void>;
  snooze(reminderId: string): Promise<void>;
  dismissReminder(reminderId: string): Promise<void>;
  onVoiceEvent(e: ServerEvent): void;
  /** Re-read settings-derived state after `settings.changed`. */
  recheckKey(): Promise<void>;
  applySettings(): Promise<void>;
  toggleVoice(): Promise<void>;
  /** Typed request through the AI (same session and tools as voice). True if it was sent. */
  ask(text: string): Promise<boolean>;
  notify(kind: Notice["kind"], text: string): void;
  dismissNotice(): void;
}

const emptyLists = (): Record<Tab, Task[]> => ({ today: [], upcoming: [], completed: [], archived: [] });

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return "Something went wrong";
}

let refreshTimer: ReturnType<typeof setTimeout> | undefined;
let noticeTimer: ReturnType<typeof setTimeout> | undefined;

export const useTasks = create<TaskState>((set, get) => {
  /** Run one mutation with busy-guarding; report success only after the server confirms it. */
  async function mutate<T>(key: string, fn: (api: Api) => Promise<T>, ok?: string): Promise<T | null> {
    const { api, busy } = get();
    if (!api || busy[key]) return null;
    set({ busy: { ...busy, [key]: true } });
    try {
      const result = await fn(api);
      if (ok) get().notify("ok", ok);
      await get().refresh();
      return result;
    } catch (e) {
      get().notify("error", errorText(e));
      return null;
    } finally {
      const { [key]: _, ...rest } = get().busy;
      set({ busy: rest });
    }
  }

  return {
    api: null,
    backend: "starting",
    tz: undefined,
    tab: "today",
    lists: emptyLists(),
    reminders: { attention: [], upcoming: [] },
    loaded: false,
    busy: {},
    notice: null,
    editorOpen: false,
    voice: null,
    transcript: [],
    hasKey: null,

    async connect(info) {
      const api = new Api(info);
      set({ api, backend: info.status });
      if (info.status !== "ready") return;
      await get().applySettings();
      void get().recheckKey();
      api.voiceStatus().then((voice) => set({ voice }), () => {});
      await get().refresh();
    },

    setBackendStatus(s) {
      set({ backend: s });
    },

    setTab(tab) {
      set({ tab });
    },

    setEditorOpen(editorOpen) {
      set({ editorOpen });
    },

    async refresh() {
      const { api } = get();
      if (!api) return;
      // Coalesce bursts (our own mutation + its WS echo) into one round of local requests.
      clearTimeout(refreshTimer);
      await new Promise<void>((resolve) => {
        refreshTimer = setTimeout(resolve, 30);
      });
      try {
        const [reminders, ...results] = await Promise.all([api.listReminders(), ...TABS.map((t) => api.listTasks(t))]);
        const lists = emptyLists();
        TABS.forEach((t, i) => (lists[t] = results[i].items));
        set({ lists, reminders, loaded: true, backend: "ready" });
      } catch (e) {
        if (e instanceof ApiError && e.code === "offline") set({ backend: "down" });
        else get().notify("error", errorText(e));
      }
    },

    create: (body) => mutate("new", (api) => api.createTask({ source: "ui", ...body }), "Task saved"),
    update: (id, patch) => mutate(id, (api) => api.updateTask(id, patch), "Task updated"),

    async toggleComplete(task) {
      await mutate(task.id, (api) =>
        task.status === "completed" ? api.reopenTask(task.id) : api.completeTask(task.id),
      );
    },

    async archive(id) {
      await mutate(id, (api) => api.archiveTask(id), "Task archived — restore it from Archived");
    },

    async restore(id) {
      await mutate(id, (api) => api.reopenTask(id), "Task restored");
    },

    async snooze(reminderId) {
      await mutate(reminderId, (api) => api.snoozeReminder(reminderId), "Snoozed");
    },

    async dismissReminder(reminderId) {
      await mutate(reminderId, (api) => api.dismissReminder(reminderId));
    },

    async applySettings() {
      const { api } = get();
      if (!api) return;
      try {
        const s = await api.getSettings();
        set({ tz: s.tasks.timezone ?? undefined });
        applyAppearance(s.appearance, { dot: false });
      } catch {
        /* settings are optional for rendering; tz falls back to the system zone */
      }
    },

    async recheckKey() {
      try {
        const k = await get().api?.apiKeyStatus();
        if (k) set({ hasKey: k.has_api_key });
      } catch {
        /* unknown: keep hiding the onboarding card */
      }
    },

    onVoiceEvent(e) {
      if (e.type === "voice.state") set({ voice: e.payload as unknown as VoiceStatus });
      else if (e.type === "voice.transcript") set({ transcript: addTranscript(get().transcript, e.payload as unknown as TranscriptLine) });
    },

    async toggleVoice() {
      const { api, voice } = get();
      if (!api) return;
      const active = voice?.mic_active || voice?.state === "processing" || voice?.state === "speaking";
      try {
        set({ voice: await (active ? api.voiceStop() : api.voiceStart()) });
      } catch (e) {
        get().notify("error", errorText(e));
      }
    },

    async ask(text) {
      const { api } = get();
      if (!api) return false;
      try {
        const voice = await api.voiceText(text);
        set({ voice });
        return voice.state !== "error";
      } catch (e) {
        get().notify("error", errorText(e));
        return false;
      }
    },

    notify(kind, text) {
      clearTimeout(noticeTimer);
      set({ notice: { kind, text, id: Date.now() } });
      noticeTimer = setTimeout(() => set({ notice: null }), kind === "error" ? 6000 : 2500);
    },

    dismissNotice() {
      clearTimeout(noticeTimer);
      set({ notice: null });
    },
  };
});
