import { useCallback, useEffect, useRef, useState } from "react";
import { applyAppearance } from "../lib/appearance";
import { setLaunchAtLogin } from "../lib/startup";
import { formatDue } from "../lib/time";
import { Api } from "../services/api";
import { getBackendInfo, isTauri, onBackendStatus } from "../services/backend";
import { showPanel } from "../services/windows";
import type { BackendInfo, Reminder, ServerEvent, VoiceStatus } from "../types";
import { useEvents } from "./useEvents";

/** Pure: the desktop notification text for a reminder (PRD §7.2 step 6). */
export function notificationFor(r: Reminder, tz?: string): { title: string; body: string } {
  const due = r.task_due_at ? `Due ${formatDue(r.task_due_at, tz)}` : "Ziko reminder";
  if (r.missed) return { title: `Missed: ${r.task_title}`, body: `Was set for ${formatDue(r.fire_at, tz)} · ${due}` };
  return { title: r.task_title, body: due };
}

async function showNotification(title: string, body: string): Promise<void> {
  const { isPermissionGranted, requestPermission, sendNotification } = await import("@tauri-apps/plugin-notification");
  let granted = await isPermissionGranted();
  if (!granted) granted = (await requestPermission()) === "granted";
  if (granted) sendNotification({ title, body });
}

export interface DotStatus {
  /** Fired reminders still waiting for Snooze / Dismiss (the badge). */
  alerts: number;
  voice: VoiceStatus | null;
  startVoice(): Promise<void>;
  setMuted(muted: boolean): Promise<void>;
}

/**
 * Runs in the always-alive dot window, so reminders reach the user while the panel is hidden (PRD §7.1)
 * and the dot can show the voice state (PRD §4.3). The backend decides *when* a reminder fires; this only
 * shows what it sends.
 */
export function useDotStatus(onWake?: () => void): DotStatus {
  const wakeRef = useRef(onWake);
  wakeRef.current = onWake;
  const [info, setInfo] = useState<BackendInfo | null>(null);
  const [pending, setPending] = useState(0);
  const [voice, setVoice] = useState<VoiceStatus | null>(null);
  const api = useRef<Api | null>(null);
  const tz = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!isTauri()) return;
    void getBackendInfo().then(setInfo);
    const off = onBackendStatus(setInfo);
    return () => void off.then((u) => u());
  }, []);

  const recount = useCallback(async () => {
    try {
      setPending((await api.current?.listReminders())?.attention.length ?? 0);
    } catch {
      /* backend restarting: keep the last count */
    }
  }, []);

  const firstLoad = useRef(true);
  const loadSettings = useCallback(async () => {
    try {
      const s = await api.current!.getSettings();
      tz.current = s.tasks.timezone ?? undefined;
      applyAppearance(s.appearance, { dot: true });
      if (firstLoad.current) {
        firstLoad.current = false;
        void setLaunchAtLogin(s.general.launch_at_startup).catch(() => {}); // OS login item follows the setting
        if (!s.general.start_minimized && isTauri()) void showPanel();
      }
    } catch {
      /* backend restarting: keep the current look */
    }
  }, []);

  useEffect(() => {
    if (info?.status !== "ready") return;
    api.current = new Api(info);
    void loadSettings();
    void recount();
    api.current.voiceStatus().then(setVoice, () => {});
  }, [info, recount, loadSettings]);

  const onEvent = useCallback(
    (e: ServerEvent) => {
      if (e.type === "reminder.due") {
        const { title, body } = notificationFor(e.payload.reminder as Reminder, tz.current);
        void showNotification(title, body).catch((err) => console.error("notification failed", err));
      }
      if (e.type.startsWith("reminder.") || e.type === "task.changed") void recount();
      if (e.type === "voice.state") setVoice(e.payload as unknown as VoiceStatus);
      if (e.type === "voice.wake") wakeRef.current?.(); // "Hey Ziko" heard locally
      if (e.type === "settings.changed") void loadSettings();
    },
    [recount, loadSettings],
  );
  useEvents(info?.status === "ready" ? info.ws_url : null, onEvent);

  const startVoice = useCallback(async () => {
    const v = await api.current?.voiceStart().catch(() => null);
    if (v) setVoice(v);
  }, []);
  const setMuted = useCallback(async (muted: boolean) => {
    const v = await api.current?.voiceMute(muted).catch(() => null);
    if (v) setVoice(v);
  }, []);
  return { alerts: pending, voice, startVoice, setMuted };
}
