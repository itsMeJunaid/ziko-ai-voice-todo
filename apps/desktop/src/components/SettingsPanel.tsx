import { useEffect, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { GLASS_PREFS } from "../lib/glass";
import type { GlassPref, GlassSupport } from "../lib/glass";
import { setLaunchAtLogin } from "../lib/startup";
import { isTauri } from "../services/backend";
import type { Theme } from "../lib/theme";
import { errorText, useTasks } from "../stores/tasks";
import type { ApiKeyStatus, AppSettings, KeyTest, SettingsPatch } from "../types";
import { IconClose } from "./icons";
import { KeyForm } from "./KeyForm";

const KEY_URL = "https://aistudio.google.com/apikey";
const GLASS_LABEL: Record<GlassPref, string> = { auto: "Auto", frosted: "Frosted", clear: "Clear", solid: "Solid" };

function timezones(): string[] {
  try {
    return (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf("timeZone");
  } catch {
    return ["UTC", "Asia/Karachi", "Asia/Dubai", "Europe/London", "Europe/Berlin", "America/New_York", "America/Los_Angeles"];
  }
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="px-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">{title}</h3>
      <div className="glass flex flex-col divide-y divide-line rounded-2xl">{children}</div>
    </section>
  );
}

function Row({ label, hint, htmlFor, children }: { label: string; hint?: string; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 px-3.5 py-2.5">
      <div className="min-w-0 flex-1">
        <label htmlFor={htmlFor} className="block text-sm font-medium text-fg">{label}</label>
        {hint && <p className="text-[11px] leading-snug text-muted">{hint}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

/** Text that saves when you leave the field or press Enter (not on every keystroke). */
function SaveOnBlur({ id, value, maxLength, onSave }: { id: string; value: string; maxLength: number; onSave: (v: string) => void }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    const v = draft.trim();
    if (v && v !== value) onSave(v);
    else setDraft(value);
  };
  return (
    <input
      id={id}
      className="field !w-[130px] !py-1.5 text-xs"
      value={draft}
      maxLength={maxLength}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
    />
  );
}

function Toggle({ id, checked, onChange, label }: { id: string; checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className="relative h-6 w-11 rounded-full transition-colors"
      style={{ background: checked ? "var(--z-cta)" : "var(--z-track)" }}
    >
      <span
        className={`absolute top-0.5 h-5 w-5 rounded-full shadow transition-all ${checked ? "left-[22px]" : "left-0.5"}`}
        style={{ background: checked ? "var(--z-cta-fg)" : "var(--z-fg)" }}
      />
    </button>
  );
}

function Choice<T extends string | number>({ id, value, options, onChange }: {
  id: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void;
}) {
  const list = options.some((o) => o.value === value) ? options : [...options, { value, label: String(value) }];
  return (
    <select
      id={id}
      className="field !w-auto max-w-[150px] truncate !py-1.5 !pr-7 text-xs"
      value={String(value)}
      onChange={(e) => {
        const o = list.find((x) => String(x.value) === e.target.value);
        if (o) onChange(o.value);
      }}
    >
      {list.map((o) => (
        <option key={String(o.value)} value={String(o.value)}>{o.label}</option>
      ))}
    </select>
  );
}

function Segmented<T extends string | number>({ name, value, options, onChange, disabled }: {
  name: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; disabled?: (v: T) => boolean;
}) {
  return (
    <div role="radiogroup" aria-label={name} className="flex gap-1 rounded-full border border-line bg-field p-1">
      {options.map((o) => {
        const on = o.value === value;
        const off = disabled?.(o.value) ?? false;
        return (
          <button
            key={String(o.value)}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={off}
            onClick={() => onChange(o.value)}
            className={`rounded-full px-2.5 py-1 text-[11px] font-semibold transition-colors disabled:opacity-35 ${on ? "shadow-sm" : "text-muted hover:text-fg"}`}
            style={on ? { background: "var(--z-cta)", color: "var(--z-cta-fg)" } : undefined}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Gemini key, first and plain: what state it's in, and the three things you can do with it. */
function ApiKeyCard() {
  const api = useTasks((s) => s.api);
  const recheck = useTasks((s) => s.recheckKey);
  const notify = useTasks((s) => s.notify);
  const [key, setKey] = useState<ApiKeyStatus | null>(null);
  const [replacing, setReplacing] = useState(false);
  const [test, setTest] = useState<KeyTest | "testing" | null>(null);
  const [copied, setCopied] = useState(false);

  const load = () => void api?.apiKeyStatus().then(setKey, () => {});
  useEffect(load, [api]);

  const runTest = async () => {
    if (!api) return;
    setTest("testing");
    setTest(await api.testKey().catch((e) => ({ ok: false as const, code: "error", message: errorText(e) })));
  };
  const remove = async () => {
    if (!api) return;
    await api.deleteApiKey();
    setTest(null);
    load();
    void recheck();
    notify("ok", "Key removed. Voice is off; your tasks still work.");
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(KEY_URL);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the link is selectable text */
    }
  };

  const has = key?.has_api_key;
  const status =
    test === "testing" ? "Testing…" : test?.ok ? `Connected · ${test.model}` : test ? test.message : has ? "Key saved" : "No key yet — voice is off";

  return (
    <div className="flex flex-col gap-3 px-3.5 py-3.5">
      <div className="flex items-center gap-2.5">
        <span
          aria-hidden
          className={`h-2.5 w-2.5 shrink-0 rounded-full ${test && test !== "testing" && !test.ok ? "bg-danger" : ""}`}
          style={test && test !== "testing" && !test.ok ? undefined : { background: has ? "var(--z-fg)" : "var(--z-track)" }}
        />
        <p role="status" className={`min-w-0 flex-1 text-sm font-semibold ${test && test !== "testing" && !test.ok ? "text-danger" : "text-fg"}`}>
          {status}
        </p>
      </div>

      {has && !replacing ? (
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => void runTest()} disabled={test === "testing"} className="btn-cta px-3.5 py-1.5 text-xs">
            Test connection
          </button>
          <button type="button" onClick={() => setReplacing(true)} className="btn-ghost px-3.5 py-1.5 text-xs">Replace key</button>
          <button type="button" onClick={() => void remove()} className="btn-ghost px-3.5 py-1.5 text-xs !text-danger">Remove</button>
        </div>
      ) : (
        <>
          <KeyForm
            compact
            onSaved={() => {
              setReplacing(false);
              setTest(null);
              load();
              void recheck();
            }}
          />
          {replacing && (
            <button type="button" onClick={() => setReplacing(false)} className="self-start text-[11px] font-semibold text-muted underline">
              Keep the current key
            </button>
          )}
        </>
      )}

      <p className="text-[11px] leading-relaxed text-muted">
        Everyone uses their own free key from{" "}
        <span className="select-text font-semibold text-fg">aistudio.google.com/apikey</span>{" "}
        <button type="button" onClick={() => void copy()} className="font-semibold underline">{copied ? "copied" : "copy link"}</button>.
        It stays on this computer, in the system keychain, and is never shown again. Usage counts against
        that Google account and may be billed depending on its plan.
      </p>
    </div>
  );
}

/**
 * PRD §3.3 settings (MVP set), grouped by what people look for. Every change saves at once — no Save
 * button to forget — and is broadcast so the dot applies it live.
 */
export function SettingsPanel({ onClose, theme, onTheme, glassPref, onGlass, glassSupport }: {
  onClose: () => void;
  theme: Theme;
  onTheme: (t: Theme) => void;
  glassPref: GlassPref;
  onGlass: (g: GlassPref) => void;
  glassSupport: GlassSupport | null;
}) {
  const reduce = useReducedMotion();
  const api = useTasks((s) => s.api);
  const notify = useTasks((s) => s.notify);
  const refresh = useTasks((s) => s.refresh);
  const [s, setS] = useState<AppSettings | null>(null);
  const [devices, setDevices] = useState<string[]>([]);
  const [voices, setVoices] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState("");
  const savedTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const zones = useMemo(timezones, []);
  const [version, setVersion] = useState("dev");

  useEffect(() => {
    if (isTauri()) void import("@tauri-apps/api/app").then((m) => m.getVersion()).then(setVersion, () => {});
  }, []);

  useEffect(() => {
    if (!api) return;
    void api.getSettings().then(setS, (e) => notify("error", errorText(e)));
    void api.micDevices().then((d) => setDevices(d.devices), () => {});
    void api.geminiVoices().then((v) => setVoices(v.voices), () => {});
  }, [api, notify]);

  const flashSaved = () => {
    setSaved(true);
    clearTimeout(savedTimer.current);
    savedTimer.current = setTimeout(() => setSaved(false), 1500);
  };

  const save = async (patch: SettingsPatch) => {
    if (!api || !s) return;
    try {
      setS(await api.patchSettings(patch));
      flashSaved();
    } catch (e) {
      notify("error", errorText(e));
    }
  };

  const deleteAll = async () => {
    if (!api || confirmDelete !== "DELETE") return;
    try {
      await api.deleteAllTasks();
      setConfirmDelete("");
      notify("ok", "All tasks deleted");
      await refresh();
    } catch (e) {
      notify("error", errorText(e));
    }
  };

  return (
    <motion.div
      className="sheet absolute inset-0 z-40 flex flex-col rounded-[28px] border border-line"
      initial={reduce ? false : { opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduce ? undefined : { opacity: 0, y: 24 }}
      transition={{ type: "spring", stiffness: 420, damping: 36 }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
    >
      <div className="flex items-center justify-between px-5 pb-2 pt-5">
        <h2 id="settings-title" className="text-lg font-bold tracking-tight text-fg">Settings</h2>
        <div className="flex items-center gap-2">
          <span role="status" className={`text-[11px] font-semibold text-muted transition-opacity ${saved ? "opacity-100" : "opacity-0"}`}>✓ Saved</span>
          <button type="button" onClick={onClose} className="icon-btn" aria-label="Close settings">
            <IconClose />
          </button>
        </div>
      </div>

      {!s ? (
        <div className="m-5 h-40 animate-pulse rounded-2xl bg-card" aria-hidden />
      ) : (
        <div className="scroll-area flex flex-1 flex-col gap-5 overflow-y-auto px-5 pb-5">
          <Section title="Gemini API key">
            <ApiKeyCard />
          </Section>

          <Section title="Appearance">
            <Row label="Theme">
              <Segmented
                name="Theme"
                value={theme}
                options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]}
                onChange={(t) => { onTheme(t); flashSaved(); }}
              />
            </Row>
            <div className="flex flex-col gap-2 px-3.5 py-2.5">
              <span className="text-sm font-medium text-fg">Transparency</span>
              <Segmented
                name="Transparency"
                value={glassPref}
                options={GLASS_PREFS.map((g) => ({ value: g, label: GLASS_LABEL[g] }))}
                onChange={(g) => { onGlass(g); flashSaved(); }}
                disabled={(g) => glassSupport?.compositor === false && g !== "solid" && g !== "auto"}
              />
            </div>
            <Row label="Pet size" hint="The little robot in the corner">
              <Segmented
                name="Pet size"
                value={s.appearance.dot_size}
                options={[{ value: 36, label: "S" }, { value: 44, label: "M" }, { value: 52, label: "L" }]}
                onChange={(v) => void save({ appearance: { dot_size: v } })}
              />
            </Row>
            <Row label="Pet visibility" htmlFor="po">
              <Choice
                id="po"
                value={s.appearance.dot_opacity}
                options={[{ value: 1, label: "100%" }, { value: 0.95, label: "95%" }, { value: 0.8, label: "80%" }, { value: 0.6, label: "60%" }]}
                onChange={(v) => void save({ appearance: { dot_opacity: v } })}
              />
            </Row>
          </Section>

          <Section title="Voice">
            <Row label="What should Ziko call you?" hint="Used in greetings and replies" htmlFor="callme">
              <SaveOnBlur id="callme" value={s.voice.call_me} maxLength={30} onSave={(v) => void save({ voice: { call_me: v } })} />
            </Row>
            <Row label="Greet me when I say “Hey Ziko”" hint={`“Hi ${s.voice.call_me}! How's it going?” plus today at a glance`} htmlFor="greet">
              <Toggle id="greet" label="Greeting" checked={s.voice.greet_on_wake} onChange={(v) => void save({ voice: { greet_on_wake: v } })} />
            </Row>
            <Row label="Listen for “Hey Ziko”" hint="Heard on this computer; nothing is sent until you say it" htmlFor="ww">
              <Toggle id="ww" label="Wake word" checked={s.voice.wake_word_enabled} onChange={(v) => void save({ voice: { wake_word_enabled: v } })} />
            </Row>
            <Row label="Wake word sensitivity" hint="Raise it if Ziko misses you; lower it if it wakes by itself" htmlFor="wwt">
              <Choice
                id="wwt"
                value={s.voice.wake_word_threshold}
                options={[{ value: 0.9, label: "Strict" }, { value: 0.8, label: "Balanced" }, { value: 0.65, label: "Sensitive" }]}
                onChange={(v) => void save({ voice: { wake_word_threshold: v } })}
              />
            </Row>
            <Row label="Turn the mic off after" hint="Seconds of silence in a conversation" htmlFor="sil">
              <Choice
                id="sil"
                value={s.ai.interaction_timeout_s}
                options={[5, 10, 20, 30].map((n) => ({ value: n, label: `${n} s` }))}
                onChange={(v) => void save({ ai: { interaction_timeout_s: v } })}
              />
            </Row>
            <Row label="Spoken replies" hint="Off: Ziko answers in text only" htmlFor="vr">
              <Toggle id="vr" label="Spoken replies" checked={s.voice.voice_replies_enabled} onChange={(v) => void save({ voice: { voice_replies_enabled: v } })} />
            </Row>
            <Row label="Ziko's voice" htmlFor="gv">
              <Choice
                id="gv"
                value={s.voice.gemini_voice ?? ""}
                options={[{ value: "", label: "Default" }, ...voices.map((v) => ({ value: v, label: v }))]}
                onChange={(v) => void save({ voice: { gemini_voice: v || null } })}
              />
            </Row>
            <Row label="Microphone" htmlFor="mic">
              <Choice
                id="mic"
                value={s.voice.mic_device ?? ""}
                options={[{ value: "", label: "System default" }, ...devices.map((d) => ({ value: d, label: d }))]}
                onChange={(v) => void save({ voice: { mic_device: v || null } })}
              />
            </Row>
          </Section>

          <Section title="Tasks">
            <Row label="Default priority">
              <Segmented
                name="Default priority"
                value={s.tasks.default_priority}
                options={[{ value: "low", label: "Low" }, { value: "medium", label: "Medium" }, { value: "high", label: "High" }]}
                onChange={(v) => void save({ tasks: { default_priority: v } })}
              />
            </Row>
            <Row label="Remind me before a deadline" hint="When you ask for a reminder without a time" htmlFor="ro">
              <Choice
                id="ro"
                value={s.tasks.default_reminder_offset_min}
                options={[5, 10, 15, 30, 60].map((n) => ({ value: n, label: `${n} min` }))}
                onChange={(v) => void save({ tasks: { default_reminder_offset_min: v } })}
              />
            </Row>
            <Row label="Snooze for" htmlFor="sz">
              <Choice
                id="sz"
                value={s.tasks.snooze_minutes}
                options={[5, 10, 15, 30].map((n) => ({ value: n, label: `${n} min` }))}
                onChange={(v) => void save({ tasks: { snooze_minutes: v } })}
              />
            </Row>
            <Row label="Timezone" htmlFor="tz">
              <Choice
                id="tz"
                value={s.tasks.timezone ?? ""}
                options={[{ value: "", label: "System" }, ...zones.map((z) => ({ value: z, label: z }))]}
                onChange={(v) => void save({ tasks: { timezone: v || null } })}
              />
            </Row>
          </Section>

          <Section title="General">
            <Row label="Start Ziko when I log in" htmlFor="las">
              <Toggle
                id="las"
                label="Start at login"
                checked={s.general.launch_at_startup}
                onChange={(v) =>
                  void setLaunchAtLogin(v).then(
                    () => save({ general: { launch_at_startup: v } }),
                    (e) => notify("error", `Couldn't change startup: ${errorText(e)}`),
                  )
                }
              />
            </Row>
            <Row label="Open the panel when Ziko starts" hint="Off: only the pet appears" htmlFor="sm">
              <Toggle id="sm" label="Open panel at start" checked={!s.general.start_minimized} onChange={(v) => void save({ general: { start_minimized: !v } })} />
            </Row>
          </Section>

          <Section title="Privacy & data">
            <div className="flex flex-col gap-2 px-3.5 py-3 text-[11px] leading-relaxed text-muted">
              <p>Tasks and reminders stay in a database on this computer. “Hey Ziko” is detected locally.</p>
              <p>
                After you wake Ziko or press the mic, your voice and typed requests go to Google's Gemini API to be
                understood. Ziko doesn't record audio or save conversations; how long Google keeps requests depends on
                the plan of the key you use.
              </p>
            </div>
            <div className="flex flex-col gap-2 px-3.5 py-3">
              <label htmlFor="del" className="text-sm font-medium text-fg">Delete all tasks</label>
              <p className="text-[11px] text-muted">Permanently removes every task and reminder. Type DELETE to confirm.</p>
              <div className="flex gap-2">
                <input id="del" className="field min-w-0 flex-1" value={confirmDelete} onChange={(e) => setConfirmDelete(e.target.value)} placeholder="DELETE" autoComplete="off" />
                <button type="button" disabled={confirmDelete !== "DELETE"} onClick={() => void deleteAll()} className="btn-ghost shrink-0 !text-danger disabled:opacity-40">
                  Delete
                </button>
              </div>
            </div>
            <div className="px-3.5 py-2.5">
              <button
                type="button"
                onClick={() => void api?.resetSettings().then((r) => { setS(r); notify("ok", "Settings reset to defaults"); })}
                className="text-[11px] font-semibold text-muted underline hover:text-fg"
              >
                Reset all settings to defaults
              </button>
            </div>
          </Section>
          <p className="text-center text-[10px] text-faint">Ziko {version} · AI model {s.ai.model}</p>
        </div>
      )}
    </motion.div>
  );
}
