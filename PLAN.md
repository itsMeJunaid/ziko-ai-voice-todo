# Ziko — Build Plan (3-Day MVP)

**Source:** the Ziko PRD v1.0 (private, not included in this repository)
**Constraints:** solo developer · 3 days (~10 h/day, AI-assisted) · Windows first
**Wake word:** LiveKit wakeword (open source, Apache-2.0) as the primary engine; Porcupine kept as a tested fallback adapter behind the same interface. Decision changed 2026-10-26 after research.
**Plan date:** 2026-10-26

---

## 0. PRD analysis

### What the PRD gets right (treat as the spec)
- §4.3 explicit voice state machine (Idle / Listening / Processing / Speaking / Interrupted / Error / Muted).
- §5.4 closed tool list (11 tools) — the model never touches the DB.
- §7.4 reminder reliability rules — persisted, idempotent, rebuilt on startup, reconciled after sleep.
- §9.2 / §12 "never report success before the operation succeeded" + failure table.
- §14 acceptance checklist — reproduced at the bottom of this file and ticked per phase.

### Open questions the PRD leaves to implementation — resolved (research 2026-10-26)

| PRD question | Finding | Decision |
|---|---|---|
| Which Gemini Live model exists now? (§4.4) | `gemini-3.8-live` is the stable default Live model. Also listed: `gemini-3.8-live-extended-thinking` (stable), `gemini-3.1-flash-live-preview` (legacy), `gemini-2.5-flash-native-audio-preview-12-2025`. Function calling is supported (sync + async). Google notes audio in/out reduces tool-call reliability. | Default `gemini-3.8-live`, configurable in settings. Fallback `gemini-2.5-flash-native-audio-preview-12-2025`. Confirm in Phase 0 with a real key. |
| Is openWakeWord viable on Windows? (§4.2) | openWakeWord: last release v0.6.0 (Feb 2024), no "Hey Ziko" model, training needs pinned 2022-era TF/PyTorch. **livekit-wakeword 0.3.0** (Apache-2.0, 2026): runtime deps are only numpy + onnxruntime; one-command training from TTS-generated data (`livekit-wakeword run config.yaml`) exports an openWakeWord-compatible ONNX; Python `WakeWordModel.predict()` on 16 kHz frames. Windows is not explicitly documented; onnxruntime runs there. | **Primary: livekit-wakeword** with a self-trained "Hey Ziko" ONNX. **Fallback: Porcupine** (console-trained `.ppn`, free personal tier) if training quality or Windows inference disappoints. Both behind the `WakeWordDetector` protocol. |
| How to ship the Python backend with Tauri? (§8.5) | Tauri 2 `bundle.externalBin` sidecar + PyInstaller is the documented path. Binary needs the target-triple suffix and `.exe`; requires the shell plugin. Known NSIS reinstall bug can leave a stale sidecar. | Dev: Tauri spawns `uv run uvicorn`. Release: PyInstaller `--onefile` sidecar. |
| Transparent always-on-top floating window on Windows (Risk 6) | Works in Tauri 2 (`transparent`, `alwaysOnTop`, `decorations:false`). Known shadow/border quirk on Win10/11; a second WebView2 window must share `additional_browser_args`. | Two windows: `dot` and `panel`. Verified in Phase 0 spike. |

### Where the PRD over-specifies for a 3-day MVP
~45 settings items (§3.3), Urdu validation (§4.5), notification history, quiet hours, overdue/retention policies, About/licenses/update check. These become fixed defaults or v1.1 (see §2).

---

## 1. Architecture decisions

1. **Transport.** FastAPI bound to `127.0.0.1` on a random free port. Tauri generates a per-launch random token and passes `ZIKO_TOKEN` + `ZIKO_PORT` to the sidecar via env. Every request carries `Authorization: Bearer <token>`. REST for tasks/reminders/settings. One WebSocket `/ws/events` pushes `voice.state`, `voice.transcript`, `task.changed`, `reminder.due`, `backend.status`. The frontend never touches SQLite or the Gemini key.
2. **All audio lives in Python.** One `sounddevice` 16 kHz mono input stream feeds Porcupine while Idle; after detection the same stream is forwarded to Gemini Live (16 kHz PCM in). 24 kHz PCM out is played via `sounddevice`. This avoids WebView mic permissions and double mic ownership. Barge-in uses Gemini's server-side VAD/interruption; a `half_duplex` flag mutes mic forwarding during playback if the spike shows echo re-triggering.
3. **Gemini Live service.** `LiveSessionManager` (connect on demand, reconnect ≤3× with backoff, close after idle timeout) + `ToolRegistry` (Pydantic-validated declarations for the 11 PRD tools) + `dispatch(tool_call) -> result` → `send_tool_response`. System-prompt rules: call `get_current_datetime` before resolving relative dates; emit ISO-8601 with offset; never confirm before the tool result; if a title matches more than one task, ask which.
4. **Dates.** Tools accept ISO-8601 with offset. Backend normalises to UTC, stores UTC, renders in the configured timezone. No local NL date parser in the MVP (the model resolves dates; the UI uses a date-time picker).
5. **Reminders = DB-polled scheduler, not APScheduler.** `reminders` table with state enum `scheduled | delivering | delivered | snoozed | dismissed | cancelled | missed | failed`. An asyncio loop ticks every 1 s and atomically claims due rows (`UPDATE … WHERE state='scheduled' AND fire_at<=now RETURNING`). Startup and a monotonic-clock gap > 30 s (sleep/resume) trigger reconciliation: overdue rows become `missed` and are delivered once with a "missed" label. Persisted, idempotent, restart-safe by construction.
6. **Notifications.** Backend emits `reminder.due` over WS; the always-alive `dot` window calls `@tauri-apps/plugin-notification`. If no WS client is connected, backend falls back to `winotify`. Delivered state is written by the backend after emit/ack.
7. **Windows.** `dot` (64×64, transparent, alwaysOnTop, skipTaskbar, no decorations) and `panel` (420×640, same flags, hidden by default, positioned beside the dot, hides on blur). Position persisted with `tauri-plugin-store` and clamped to `availableMonitors()` on start and on monitor change.
8. **Settings.** One typed Pydantic `Settings` row in SQLite. **API key** in Windows Credential Manager via `keyring`; the API only ever returns `has_api_key: bool`.
9. **Backend lifecycle.** `tauri-plugin-single-instance`; spawn sidecar → poll `/health` (≤10 s) → ready; on sidecar exit emit `backend.status` and auto-restart once; kill on app exit.
10. **Soft delete.** `archive_task` sets `status=archived`. A hard delete exists only in Settings ("Delete all local tasks").

---

## 2. Scope

### In (maps to §14 acceptance)
Floating dot, drag + persist, panel (Today / Upcoming / Completed), manual task CRUD, archive, tray (Open / Mute / Quit), settings persistence, reminders with notification + snooze (+10 min) / dismiss + restart/resume reconciliation, Gemini Live voice with the 11 tools, text-input path when AI is down, voice-state orb, mute, wake word via Porcupine, autostart, API-key setup flow, packaged installer.

### Fixed defaults instead of settings
Overdue behaviour (stays in Today, red). Completed retention 30 days. Quiet hours off. Snooze 10 min. Reminder sound = OS default. Font size, animation intensity, panel transparency fixed. Dark theme only.

### Deferred to v1.1
Urdu / mixed-language validation · notification history · About / licenses / update check · double-click configurability (double-click = voice, fixed) · diagnostics viewer (logs are files) · reduced-motion toggle (respect OS `prefers-reduced-motion` only) · openWakeWord support beyond what livekit-wakeword's ONNX compatibility already gives.

---

## 3. Phases

### Phase 0 — Spikes & scaffold · Day 1, 09:00–12:00 · 🟡 Gemini ✅ · wake word ✅ · native window spike pending (WebKit / Windows)
**Goal:** kill the three risks the PRD flags before writing product code.

1. `spikes/gemini_live.py` — connect with `google-genai`, model `gemini-3.8-live`; send text "add a task tomorrow 10am"; declare one tool `create_task`; assert a `tool_call` arrives; send the tool response; receive audio bytes and play them. Record first-audio latency. Confirm `gemini-2.5-flash-native-audio-preview-12-2025` as fallback. **Lock the model ID here.** ✅ **PASS** — `gemini-3.8-live`, 1.8 s first audio, datetime→create_task in order; fallback works but ignored the clock (UTC offset).
2. Wake word: train `hey_ziko.onnx` ✅ v2 trained (10k clips, sound-alike negatives); real voice scores 0.82–0.96, threshold **0.8**, 0 FP in silence, 7% CPU (0.3.0 `run` has an extraction bug: see README / `spikes/train_finish.py`). `spikes/wakeword_livekit.py` with `WakeWordModel` + `sounddevice`: 20 utterances, log hits / misses / false positives over 5 min idle. Fallback `spikes/wakeword.py` (Porcupine) stays available.
3. `spikes/tauri-window` — `tauri create`; transparent always-on-top frameless 64×64 window; drag; second window. Confirm on Windows (shadow quirk, WebView2 args).
4. Scaffold the monorepo (§4 structure): `uv` + pinned `pyproject.toml`; Tauri 2 + React + TS + Tailwind + Framer Motion; pytest; vitest; `.env.example`; README stub.

**Done when:** all three spikes pass on the target laptop; model ID and `hey_ziko.onnx` metrics recorded in README.

### Phase 1 — Backend core & task CRUD · Day 1, 13:00–18:00
**Goal:** a correct, tested local task API with no AI.

1. `backend/app/models/{task,reminder,settings}.py` — SQLAlchemy 2, UUID PK, CHECK constraints for enums, `DateTime(timezone=True)` in UTC. Alembic init + first migration.
2. `schemas/` Pydantic request/response. `services/task_service.py` (create / list / get / update / complete / archive, transactional; `find_by_title` returns candidates for disambiguation). `services/datetime_service.py` (now, tz convert, "today window" in the configured tz). `services/settings_service.py` + `keyring` wrapper.
3. `api/` routers: `/health`, `/tasks`, `/tasks/{id}/complete|archive`, `/summary/today`, `/settings`, `/settings/api-key` (PUT / DELETE → `has_api_key`). Bearer-token middleware, localhost bind, JSON error envelope.
4. `ws/events.py` hub (fan-out; `task.changed` published by the task service).
5. Tests: status transitions; tz boundaries (23:30 local is a different UTC day); validation rejects `reminder_at > due_at`; auth rejects missing token.

**Done when:** `pytest` green; `curl` CRUD works with the token.

### Phase 2 — Desktop shell wired to backend · Day 1 evening → Day 2, 09:00–12:00 · ✅ native run on Linux (GNOME Wayland) 2026-10-26 · Windows run pending
**Goal:** a usable local to-do app (the PRD's Phase 1 + Phase 2 deliverable).

1. `src-tauri`: two windows; tray (Open / Mute / Quit); single-instance; sidecar spawn + health wait + kill on exit; token/port injection; global shortcut `Ctrl+Shift+Z`.
2. `FloatingDot.tsx` (drag via `startDragging`, idle glow, state ring); position persist + monitor clamp; click → toggle panel. `TaskPanel.tsx` with header (greeting, live clock via `setInterval`, never from the backend), tabs Today / Upcoming / Completed; `TaskCard.tsx`; add/edit modal with date-time picker; archive. `services/api.ts`, `stores/tasks.ts` (Zustand), `hooks/useEvents.ts` (WS → store).
3. Glassmorphism tokens in Tailwind config; blur via `windowEffects` if the spike shows it works on Windows, else CSS fallback.

**Done when:** §14 "Desktop UI" + "Tasks" boxes tick (except voice and clarification).

### Phase 3 — Reminder engine · Day 2, 13:00–15:30 · ✅ done 2026-10-26 (Linux live run; sleep drill on real hardware pending)
**Goal:** reminders that work with the AI off and the panel hidden.

1. `services/reminder_service.py` — create / update / cancel; completing or archiving a task cancels its scheduled reminders; `default_reminder_offset_min` applied on create when `reminder_enabled`.
2. `services/scheduler.py` — asyncio 1 s tick; atomic claim; deliver (WS `reminder.due` → Tauri notification; `winotify` fallback); mark `delivered` / `failed`; startup + sleep-gap reconciliation → `missed`; snooze (+10 min, new `scheduled` row) and dismiss endpoints.
3. `ReminderCard.tsx` in the panel's "Upcoming reminders" with Snooze / Dismiss; notification click opens the panel. *(Built: the Tauri notification plugin has no click action on desktop, so the dot shows a count badge instead and a click on it opens the panel.)*
4. Tests with an injected fake clock: fires once; survives restart (re-run scheduler on the same DB); sleep gap marks missed; complete cancels; double tick never duplicates.

**Done when:** §14 "Reminders" boxes tick.

### Phase 4 — Gemini Live voice & tools · Day 2, 15:30–21:00 · ✅ 2026-10-27 (real Gemini; in-app key; mic auto-off after 20 s silence verified live)
**Goal:** a voice assistant that operates on real tasks and never lies about results.

1. `services/audio_io.py` (sounddevice in/out, ring buffer, mute flag). `services/gemini_live_service.py` (`LiveSessionManager`: connect on demand, reconnect ≤3× backoff, close after `ai_timeout_s` silence, input + output transcription on). `tools/registry.py` + `tools/task_tools.py` for the 11 tools — each validates via Pydantic, calls the service, returns the real result or `{error}`; ambiguous matches return `candidates` so the model asks. *(Phase 0 findings: loop `session.receive()` across turns, because `gemini-3.8-live` ends a turn after every tool call; the fallback model skipped `get_current_datetime` and sent UTC, so tool args with an offset differing from the user's zone get re-anchored or rejected with a clarification.)*
2. `services/voice_service.py` state machine (`Idle → Listening → Processing → Speaking → Idle`, plus `Interrupted`, `Error`, `Muted`) publishing `voice.state` / `voice.transcript`. Endpoints `POST /voice/start`, `/voice/stop`, `/voice/text` (text turn through the same session so the UI text box works), `/voice/mute`.
3. Frontend: `VoiceOrb.tsx` (state shown as text label + shape, not colour alone), mic button, text input, transcript list, "audio transmitting" indicator, connection/error banner. When the AI is unavailable the panel shows "AI offline — manual mode" and CRUD keeps working.
4. Manual script of 12 commands: create / list / update / complete / archive / overdue / summary / ambiguous title / ambiguous date / invalid param / no internet / wrong key.

**Done when:** §14 "Voice" boxes tick except wake word.

### Phase 5 — Wake word & background behaviour · Day 3, 09:00–12:30 · ✅ 2026-10-27 (9/10 real clips, 0 false triggers offline; idle CPU 7.3% recorded; Porcupine engine not wired — LiveKit only)
**Goal:** Ziko waits quietly and wakes on "Hey Ziko".

1. `services/wakeword/base.py` (`WakeWordDetector` protocol: `feed(pcm16k) -> Detection | None`, `reset()`, `close()`); `livekit.py` implementation (`WakeWordModel` over the trained `hey_ziko.onnx`; stateless `predict()` on a rolling 2 s int16 window every 240 ms — measured ~23 ms per call, ~9% of one core idle; threshold from settings, 2 s debounce); `porcupine.py` fallback implementation (`.ppn` path + access key from settings). Engine chosen by the `wakeword.engine` setting. **Must** pass `SessionOptions` with `intra_op_num_threads=inter_op_num_threads=1` and `session.intra_op.allow_spinning=0`: defaults burn ~1800% CPU on a 20-core box (measured).
2. Idle loop: mic → detector only; on hit → `voice_service.start()`; 2 s refractory to stop double activation; mic device change/disconnect → `Error` state + retry; settings toggle; dot pulses on detection and the panel opens.
3. Autostart via `tauri-plugin-autostart` + "Start minimized". Measure idle CPU/RAM and record in README.
4. Fallbacks always present: shortcut, mic button, double-click.

**Done when:** 20-utterance test ≥ 18 hits and ≤ 1 false positive in 10 min idle; idle CPU recorded.

### Phase 6 — Settings, security, packaging · Day 3, 13:30–20:00 · ✅ Linux .deb built + release run verified 2026-10-27; Windows NSIS via `.github/workflows/build.yml` (not yet run)
**Goal:** an installable MVP that passes the §16 end-to-end scenario.

1. `SettingsPanel.tsx` (reduced set): **General** launch at startup, start minimized, reset · **Appearance** dot size, opacity, accent · **Voice** wake word on/off, voice replies on/off, Gemini voice (from the model's list), mic device, test mic / test voice · **Tasks** default priority, default reminder offset, timezone · **AI & Privacy** model, connection status, timeout, API key set / replace / remove with charge warning, clear history, delete all tasks.
2. Security pass: key never in any API response or log; logs redact task titles unless `ZIKO_DEBUG_CONTENT=1`; backend refuses non-loopback; token required on WS upgrade.
3. First-run onboarding card: paste key → test connection → done.
4. Packaging: PyInstaller sidecar (`--onefile`, `--collect-all pvporcupine google.genai sounddevice`), rename with the target triple, `tauri build` (NSIS). Install on a clean Windows user profile; run the §16 scenario; write README (install, key setup, privacy note per §11.3).

**Done when:** the installer runs the E2E scenario end-to-end on a fresh profile.

### If time slips
Drop in this order: onboarding card → appearance settings → autostart → snooze → custom-trained wake word (fall back to Porcupine, then to shortcut + mic button only).
**Never drop:** reminder reconciliation · token auth · key in keyring · "no success before commit".

---

## 4. Project structure (created in Phase 0)

```
ZikoTodo/
├─ PLAN.md                      ← this file
├─ PRD/txt                      ← source PRD (optionally move to docs/PRD.md)
├─ apps/desktop/                ← Tauri 2 + React + TS
│  ├─ src/{components,hooks,services,stores,styles}/
│  └─ src-tauri/{src/,binaries/,tauri.conf.json,capabilities/}
├─ backend/
│  ├─ app/{api,core,database,models,schemas,services,tools,ws,main.py}
│  ├─ alembic/
│  └─ tests/
├─ spikes/                      ← Phase 0 throwaway scripts
├─ .env.example
└─ README.md
```

---

## 5. Verification

- **Backend:** `uv run pytest` — task transitions, tz boundaries, reminder scheduler with fake clock, tool validation, auth.
- **Frontend:** `npm test` (vitest: store reducers, event hub); `npm run tauri dev` smoke.
- **E2E (manual, PRD §16):** start → voice-create task → appears in UI → restart → persists → voice-move deadline → DB row changed → schedule reminder +2 min → hide panel → notification fires → complete task → reminder cancelled.
- **Failure drills (PRD §12):** kill backend process → status banner → auto-restart · sleep laptop through a reminder → "missed" delivered on resume · unplug internet → manual CRUD still works · wrong API key → actionable error.

---

## 6. Acceptance checklist (PRD §14) — tick per phase

### Desktop UI (Phase 2) — native run on Ubuntu 24.04 GNOME 46 / Wayland (via XWayland), NVIDIA hybrid GPU
- [x] Ziko displays a small floating dot. *(96×96 transparent window, verified by pixel capture)*
- [x] The dot stays above normal application windows. *(`_NET_WM_STATE_ABOVE`; Wayland can't do this, so Linux runs via XWayland)*
- [x] Users can drag the dot around the screen. *(manual drag; saved position matched the window)*
- [x] Its position persists after restarting the application. *(restart restored (1818, 25))*
- [x] Clicking the dot opens the task panel. *(manual; Ctrl+Shift+Z and tray verified to toggle it)*
- [x] The task panel uses the agreed glassmorphism design. *(verified in Chrome render)*
- [x] Clicking outside closes the panel appropriately. *(manual, Linux)*
- [x] Settings can be opened and saved. *(Playwright: every change saved to the backend immediately)*
- [x] The application provides a system tray control. *(Open / Mute / Quit over StatusNotifierItem; Open toggles the panel)*

### Tasks (Phase 1–2, clarification in Phase 4)
- [x] Users can create tasks manually. *(UI e2e)*
- [x] Users can view today's tasks. *(UI e2e)*
- [x] Users can edit task details. *(UI e2e)*
- [x] Users can mark tasks complete. *(UI e2e)*
- [x] Users can archive or delete tasks. *(UI e2e; archive is recoverable)*
- [x] Tasks persist after application restarts. *(backend restart check)*
- [x] The application correctly handles local dates and timezones. *(pytest + vitest)*
- [x] Ambiguous task references trigger clarification. *(pytest: `ambiguous` + candidates; live: vague "later" → asked for a time)*

### Voice (Phase 4, wake word in Phase 5)
- [x] The configured wake word activates Ziko. *(real model on 10 real "Hey Ziko" clips: 9 hit; hand-off to the conversation tested; a spoken test by the user still recommended)*
- [x] Wake-word detection runs locally. *(ONNX model in the backend; no network involved until a hit)*
- [x] Gemini Live can receive audio and generate spoken responses. *(live: natural speech in → transcribed → spoken reply; a human at the real mic still to do)*
- [x] The user can create a task through voice. *(live audio: "water the plants tomorrow at 9 AM" → saved 09:00 local, source=voice)*
- [x] The user can list tasks through voice. *(live, same session via text turns)*
- [x] The user can update and complete tasks through voice. *(live: moved groceries; completed the exact "call mom", not the similar one)*
- [x] The user can request deletion through voice. *(live: asked "Are you sure?" and archived only after "yes")*
- [x] The UI reflects listening, processing, and speaking states. *(voice.state events tested; voice bar glyph + label, dot animation, "Mic on" chip)*
- [x] The system handles API errors without losing task data. *(pytest + live: no key / wrong key / offline (network namespace) → clear message, manual mode; dropped session keeps tasks)*
- [x] The user can mute the microphone. *(pytest: mute closes the session and blocks start; tray/dot menu wired to /voice/mute)*

### Reminders (Phase 3)
- [x] Users can create reminders. *(live: task with reminder → `scheduled` row)*
- [x] Reminders trigger desktop notifications. *(live: fired 0.12 s after its time, seen on D-Bus)*
- [x] Reminders work while the task panel is hidden. *(live: delivered by the dot window; OS fallback with no window)*
- [x] Reminder schedules survive application restarts. *(pytest: fresh scheduler on the same DB)*
- [x] Completing a task handles its future reminders correctly. *(pytest + live: cancelled / dismissed; reopen restores a future one)*
- [x] Missed reminders are reconciled after the system resumes. *(pytest with fake clock: >60 s late → `missed`, delivered once; real sleep drill still to run)*
- [x] Duplicate reminder delivery is prevented in normal recovery scenarios. *(pytest: atomic claim, crash mid-delivery → `failed` not resent, two schedulers → one delivery)*

### Settings and Reliability (Phase 6)
- [x] Startup behavior is configurable. *(Settings: start at login via the autostart plugin, open panel at start)*
- [x] Appearance settings persist. *(dot size, opacity, accent in the settings DB, applied live in both windows)*
- [x] Voice settings persist. *(wake word, sensitivity, replies, voice, mic, silence timeout)*
- [x] Reminder preferences persist. *(default offset, snooze minutes)*
- [x] API credentials are not hardcoded in the frontend. *(write-only key API, keyring)*
- [x] The backend binds to localhost by default. *(verified with ss)*
- [x] Core task functionality remains available when Gemini is unavailable. *(no key / wrong key / offline: "AI offline — manual mode", CRUD works)*
- [x] The application provides a safe exit and cleanup mechanism. *(tray Quit: app, backend and windows all gone, verified)*

---

## 7. References (verified 2026-10-26)
- Gemini models list — https://ai.google.dev/gemini-api/docs/models
- Live API tool use — https://ai.google.dev/gemini-api/docs/live-api/tools
- Gemini 3.8 Live developer guide — https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-3-8-live
- openWakeWord — https://github.com/dscripka/openWakeWord
- livekit-wakeword — https://github.com/livekit/livekit-wakeword · https://livekit.com/blog/livekit-wakeword
- pvporcupine (fallback) — https://pypi.org/project/pvporcupine
- Tauri 2 sidecar — https://v2.tauri.app/develop/sidecar
- PyInstaller + Tauri example (Voicebox) — https://docs.voicebox.sh/developer/building
- Tauri NSIS stale-sidecar issue — https://github.com/tauri-apps/tauri/issues/15134
