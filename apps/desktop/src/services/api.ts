import type { ApiKeyStatus, AppSettings, BackendInfo, KeyTest, Reminder, ReminderList, SettingsPatch, Task, TaskCreate, TaskList, TaskPatch, View, VoiceStatus } from "../types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turn the backend's {"error":{code,message,details}} envelope (or anything else) into an ApiError. */
export async function toApiError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON body */
  }
  const env = (body as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error;
  if (env?.message) return new ApiError(res.status, env.code ?? "error", env.message, env.details);
  return new ApiError(res.status, "http_error", `Request failed (${res.status})`);
}

export class Api {
  constructor(private info: Pick<BackendInfo, "base_url" | "token">) {}

  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    let res: Response;
    try {
      res = await fetch(this.info.base_url + path, {
        method,
        headers: {
          Authorization: `Bearer ${this.info.token}`,
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch {
      throw new ApiError(0, "offline", "Ziko's local service is not reachable");
    }
    if (!res.ok) throw await toApiError(res);
    return (await res.json()) as T;
  }

  listTasks = (view: View, q?: string) =>
    this.req<TaskList>("GET", `/tasks?view=${view}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
  createTask = (body: TaskCreate) => this.req<Task>("POST", "/tasks", body);
  updateTask = (id: string, patch: TaskPatch) => this.req<Task>("PATCH", `/tasks/${id}`, patch);
  completeTask = (id: string) => this.req<Task>("POST", `/tasks/${id}/complete`);
  reopenTask = (id: string) => this.req<Task>("POST", `/tasks/${id}/reopen`);
  archiveTask = (id: string) => this.req<Task>("POST", `/tasks/${id}/archive`);
  getSettings = () => this.req<AppSettings>("GET", "/settings");
  patchSettings = (patch: SettingsPatch) => this.req<AppSettings>("PATCH", "/settings", patch);
  resetSettings = () => this.req<AppSettings>("POST", "/settings/reset");
  apiKeyStatus = () => this.req<ApiKeyStatus>("GET", "/settings/api-key");
  setApiKey = (api_key: string) => this.req<ApiKeyStatus>("PUT", "/settings/api-key", { api_key });
  deleteApiKey = () => this.req<{ ok: boolean }>("DELETE", "/settings/api-key");
  /** Opens and closes a Gemini session; with no key, tests the stored one. */
  testKey = (api_key?: string) => this.req<KeyTest>("POST", "/voice/test", api_key ? { api_key } : {});
  micDevices = () => this.req<{ devices: string[]; default: string | null; error: string | null }>("GET", "/voice/devices");
  geminiVoices = () => this.req<{ voices: string[] }>("GET", "/voice/voices");
  deleteAllTasks = () => this.req<{ ok: boolean }>("DELETE", "/tasks?confirm=DELETE");
  listReminders = () => this.req<ReminderList>("GET", "/reminders");
  /** minutes omitted → the user's snooze setting (default 10). */
  snoozeReminder = (id: string, minutes?: number) =>
    this.req<Reminder>("POST", `/reminders/${id}/snooze`, minutes ? { minutes } : {});
  dismissReminder = (id: string) => this.req<Reminder>("POST", `/reminders/${id}/dismiss`);
  voiceStatus = () => this.req<VoiceStatus>("GET", "/voice");
  voiceStart = () => this.req<VoiceStatus>("POST", "/voice/start");
  voiceStop = () => this.req<VoiceStatus>("POST", "/voice/stop");
  voiceText = (text: string) => this.req<VoiceStatus>("POST", "/voice/text", { text });
  voiceMute = (muted: boolean) => this.req<VoiceStatus>("POST", "/voice/mute", { muted });
}
