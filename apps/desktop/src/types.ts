/** Mirrors backend/app/schemas/task.py and settings.py. Datetimes are ISO-8601 UTC strings ("…Z"). */
export type Priority = "low" | "medium" | "high";
export type TaskStatus = "pending" | "completed" | "archived";
export type TaskSource = "voice" | "text" | "ui";
export type View = "today" | "upcoming" | "overdue" | "pending" | "completed" | "archived" | "all";
export type Tab = "today" | "upcoming" | "completed" | "archived";

export interface Task {
  id: string;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: Priority;
  due_at: string | null;
  reminder_at: string | null;
  timezone: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  archived_at: string | null;
  source: TaskSource;
  is_overdue: boolean;
}

/** Mirrors backend/app/schemas/reminder.py. */
export type ReminderState = "scheduled" | "delivering" | "delivered" | "snoozed" | "dismissed" | "cancelled" | "missed" | "failed";

export interface Reminder {
  id: string;
  task_id: string;
  task_title: string;
  task_due_at: string | null;
  fire_at: string;
  state: ReminderState;
  delivered_at: string | null;
  /** Delivered late because Ziko was off or the computer slept. */
  missed: boolean;
}

/** `attention`: fired, not yet snoozed or dismissed. `upcoming`: next scheduled, soonest first. */
export interface ReminderList {
  attention: Reminder[];
  upcoming: Reminder[];
}

/** Mirrors backend/app/services/voice_service.py status(). */
export type VoiceState = "idle" | "listening" | "processing" | "speaking" | "interrupted" | "error" | "muted";

export interface VoiceStatus {
  state: VoiceState;
  /** The mic closes by itself after this many seconds of silence. */
  silence_timeout_s: number;
  muted: boolean;
  /** Microphone audio is currently being sent to Gemini (PRD §11.2). */
  mic_active: boolean;
  error: { code: string; message: string } | null;
  model: string | null;
}

export interface TranscriptLine {
  role: "user" | "assistant";
  text: string;
  final: boolean;
}

export interface TaskList {
  items: Task[];
  view: View;
  count: number;
}

/** Naive local wall-time strings ("YYYY-MM-DDTHH:mm") — the backend interprets them in the user's timezone. */
export interface TaskCreate {
  title: string;
  description?: string | null;
  priority?: Priority;
  due_at?: string | null;
  reminder_at?: string | null;
  reminder_enabled?: boolean;
  source?: TaskSource;
}

export type TaskPatch = Partial<Pick<TaskCreate, "title" | "description" | "priority" | "due_at" | "reminder_at">> & {
  status?: "pending" | "completed";
};

/** Mirrors backend/app/schemas/settings.py. */
export interface AppSettings {
  general: { launch_at_startup: boolean; start_minimized: boolean; keep_dot_visible: boolean; panel_autohide_seconds: number };
  appearance: { dot_size: number; dot_opacity: number; accent_color: string; theme: "dark" };
  voice: {
    wake_word_enabled: boolean;
    wake_word_engine: "livekit" | "porcupine";
    wake_word_threshold: number;
    voice_replies_enabled: boolean;
    spoken_reminders_enabled: boolean;
    gemini_voice: string | null;
    mic_device: string | null;
    double_click_activates_voice: boolean;
    /** How Ziko addresses the user ("Boss"). */
    call_me: string;
    /** "Hey Ziko" → a short hello with today's plan before listening. */
    greet_on_wake: boolean;
  };
  tasks: {
    default_priority: Priority;
    default_reminder_offset_min: number;
    default_morning_hour: number;
    default_evening_hour: number;
    snooze_minutes: number;
    completed_retention_days: number;
    timezone: string | null;
  };
  ai: { model: string; fallback_model: string; interaction_timeout_s: number; conversation_retention_days: number; show_audio_indicator: boolean };
}

export type SettingsPatch = { [G in keyof AppSettings]?: Partial<AppSettings[G]> };

export interface ApiKeyStatus {
  has_api_key: boolean;
  credential_store: "keyring" | "file" | "none";
}

export type KeyTest = { ok: true; model: string } | { ok: false; code: string; message: string };

export type BackendStatus = "starting" | "ready" | "down" | "failed";

export interface BackendInfo {
  base_url: string;
  ws_url: string;
  token: string;
  status: BackendStatus;
}

export interface ServerEvent {
  type: string;
  payload: Record<string, unknown>;
}
