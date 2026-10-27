# Ziko — developer guide

How the project is built, tested and packaged. For what Ziko is and how to use it, see the [README](../README.md).
Architecture decisions and the phase-by-phase build log are in [`PLAN.md`](../PLAN.md).

## Build installers
```bash
cd backend && uv run python scripts/build_sidecar.py   # PyInstaller → apps/desktop/src-tauri/binaries/ziko-backend-<triple>
cd ../apps/desktop && pnpm tauri build                 # Windows: NSIS + MSI · Linux: deb / rpm / AppImage
```
PyInstaller can't cross-compile, so build each OS on that OS. `.github/workflows/build.yml` runs all tests on every push
and builds the **Windows NSIS installer** on a `v*` tag or a manual run (artifact `ziko-windows-installer`).

## Repo layout
```
apps/desktop/   Tauri 2 + React + TypeScript + Tailwind (floating dot, panel, settings)
backend/        FastAPI sidecar: tasks, reminders, scheduler, Gemini Live, wake word
spikes/         Phase 0 throwaway scripts (model, wake word, window)
```

## Prerequisites
- Python 3.12 + [uv](https://docs.astral.sh/uv/) · Node 20+ + pnpm · Rust (`rustup`, minimal profile)
- **Windows (target):** WebView2 is built in. Microphone access for the Python sidecar.
- **Linux (dev box only):** Tauri needs these system packages before `cargo`/`pnpm tauri dev` will compile:
  ```bash
  sudo apt install -y libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev libsoup-3.0-dev libjavascriptcoregtk-4.1-dev build-essential libssl-dev patchelf
  ```

## Phase 0 — spikes (run these first)
```bash
cp .env.example .env            # fill GEMINI_API_KEY and PICOVOICE_ACCESS_KEY
cd backend
uv run --env-file ../.env python ../spikes/gemini_live.py       # model + tool call + audio  (PASS/FAIL + latency)

# Wake word — train "Hey Ziko" once (open source, no account). Training extras pull torch (~2 GB).
uv tool install "livekit-wakeword[train,eval,export]"          # one-off, isolated from the backend venv
livekit-wakeword setup                                          # downloads embedding models + datasets
# NLTK refuses a group-writable ~/nltk_data; a private folder sidesteps that:
export NLTK_DATA=~/.cache/ziko/nltk_data && mkdir -p -m 700 "$NLTK_DATA"
(cd .. && livekit-wakeword generate spikes/hey_ziko.yaml)      # step 1: synthetic clips (run from repo root)
# livekit-wakeword 0.3.0 `run`/`augment` crash at feature extraction (missing sess_options), so:
(cd .. && ~/.local/share/uv/tools/livekit-wakeword/bin/python -c "from livekit.wakeword.config import load_config; from livekit.wakeword.data.augment import run_augment; run_augment(load_config('spikes/hey_ziko.yaml'))")
(cd .. && ~/.local/share/uv/tools/livekit-wakeword/bin/python spikes/train_finish.py spikes/hey_ziko.yaml)  # extract→train→export→eval → spikes/out/hey_ziko/hey_ziko.onnx
uv run --env-file ../.env python ../spikes/wakeword_livekit.py  # "Hey Ziko" hits / false positives
# Fallback engine (needs PICOVOICE_ACCESS_KEY): uv run --env-file ../.env python ../spikes/wakeword.py
cd ../apps/desktop && pnpm tauri dev                            # transparent floating dot + panel window
```

## Run the backend alone (Phase 1)
```bash
cd backend
uv run --env-file ../.env python -m app.main          # binds 127.0.0.1:$ZIKO_PORT, runs migrations, needs ZIKO_TOKEN
curl http://127.0.0.1:8765/health                       # public
curl -H "Authorization: Bearer dev-token-change-me" "http://127.0.0.1:8765/tasks?view=today"
```
API surface: `GET/POST /tasks`, `GET /reminders`, `POST /reminders/{id}/snooze|dismiss`, `GET /voice`, `POST /voice/start|stop|text|mute|test`, `GET /voice/wake|devices|voices`, `GET/PATCH /tasks/{id}`, `POST /tasks/{id}/complete|reopen|archive`, `DELETE /tasks?confirm=DELETE`,
`GET /summary/today`, `GET/PUT/PATCH /settings`, `POST /settings/reset`, `GET/PUT/DELETE /settings/api-key` (write-only),
`WS /ws/events?token=…` (task.changed, reminder.*, voice.*, backend.status). Errors: `{"error":{"code","message","details"}}`.
Data lives in `%APPDATA%/Ziko` (Windows) or `~/.local/share/Ziko` (Linux): `ziko.db`, `logs/`, and `credentials.json` only when no OS keyring exists.

## Run the desktop app (Phase 2)
```bash
cd backend && uv sync                          # the shell runs backend/.venv's python directly in dev
cd ../apps/desktop && pnpm install && pnpm tauri dev
```
Tauri spawns the backend on a random loopback port with a random token, waits for `/health`, restarts it once
if it crashes, and kills it on exit. The backend also exits on its own if Tauri dies (stdin watchdog).
Controls: click the dot to toggle the panel · drag to move (position is remembered per monitor) ·
right-click for quick actions · `Ctrl+Shift+Z` from anywhere · tray icon (Open / Mute / Quit) · `Esc` closes.

**UI in a plain browser** (no Rust toolchain needed — handy for design work; the pet design sheet is at `/#/pet-preview`):
```bash
cd backend && ZIKO_TOKEN=dev-token-change-me uv run python -m app.main     # :8765
cd apps/desktop && pnpm dev                                                # http://localhost:1420/#/panel
pnpm e2e                                                                   # Playwright UI acceptance flow
```


**Transparency (header → Appearance).** Auto picks the best mode for the platform:

| Platform | Frosted (Auto) | Clear | Solid |
|---|---|---|---|
| Windows 11 / 10 | Real OS blur of the wallpaper (Mica / Acrylic), native rounded corners | See-through tint | Opaque |
| Linux with a compositor (GNOME, KDE, Wayland) | Wallpaper visible through a soft tint (Linux has no standard blur API) | See-through tint | Opaque |
| Linux X11 *without* a compositor | Forced Solid, filling the window, so nothing renders black | — | Opaque |


## Dev commands
```bash
cd backend && uv sync --extra windows      # on Windows only: adds winotify (notification fallback)
cd backend && uv run pytest                 # backend tests
cd apps/desktop && pnpm test                # frontend tests (vitest)
cd apps/desktop && pnpm typecheck           # tsc
cd apps/desktop && pnpm tauri dev           # run the desktop shell
```

## Status
| Phase | State |
|---|---|
| 0 Spikes | ✅ Gemini model, wake word, native window (Linux; Windows via CI) |
| 1 Backend | ✅ tasks, settings, keyring, auth, events |
| 2 Desktop shell | ✅ dot, panel, tray, shortcut, drag + persistence, click-outside (Linux native run) |
| 3 Reminders | ✅ 1 s scheduler, atomic claim, restart/sleep reconciliation, notifications, snooze/dismiss |
| 4 Voice | ✅ Gemini Live, 11 validated tools, state machine, barge-in, silence auto-off; verified against real Gemini |
| 5 Wake word | ✅ "Hey Ziko" local listener, hand-off to conversations, device recovery; 9/10 real clips, 0 false triggers |
| 6 Settings / security / packaging | ✅ settings, onboarding, security tests, PyInstaller sidecar, Linux .deb; Windows installer via CI |
Tests: backend `pytest` (tasks, reminders with a fake clock, tools, voice with a fake Gemini, wake word, security),
frontend `vitest`, and Playwright UI flows in `apps/desktop/e2e/` (`panel.e2e.cjs`, `settings.e2e.cjs`).

## Phase 0 results
| Spike | Result | Notes |
|---|---|---|
| Gemini Live model | ✅ `gemini-3.8-live` | Text turn "add a task … tomorrow at 10 AM": calls `get_current_datetime` **then** `create_task` with the local offset (`2026-10-27T10:00:00+0500`, parsed fine by Pydantic), speaks the confirmation; **first audio 1.8 s**. It ends a turn after each tool call, so the client must keep calling `receive()` across turns (fixed in the spike; Phase 4 must do the same). Fallback `gemini-2.5-flash-native-audio-preview-12-2025` passes too (3.9 s first audio) but skipped the clock tool and sent `+00:00` — 5 h wrong; the backend must re-anchor fallback times or reject offsets that differ from the user's zone. |
| Wake word (livekit) | ✅ v2 default, thr **0.8** | `spikes/out/hey_ziko/hey_ziko.onnx` (156 KB), trained 10000 clips / 50k steps with sound-alike negatives (`spikes/hey_ziko.yaml`); ≈ 35 min end-to-end on RTX 4050 after a one-off ~80 min dataset download. **Real voice:** v1 (4000 clips) scored 0.63–0.69 and caught 5/10; v2 scores **0.82–0.96**, guided run caught every utterance it saved (10 clips, all verified as speech) with ~2 likely misses, **0 false positives in 69 s silence**. Synthetic hard test set (19 h incl. "ziko", "hey kiko"): v2@0.8 recall 76.5%, 2.4 FP/h — FP mostly from deliberate sound-alikes. **CPU 7%** of one core with a single non-spinning onnxruntime thread (defaults spun ~1800%). Still to do: 2 min of normal talking / a video with no wake phrase → expect 0 hits. |
| Floating window | ✅ Linux 2026-10-26 | GNOME Wayland + NVIDIA: runs through XWayland (Wayland ignores always-on-top), DMABUF renderer off (stray lines), GTK chrome cleared, windows typed *utility* so window-decorating extensions skip them |
| Phase 2 desktop shell | ✅ native run 2026-10-26 | Panel UI verified in Chrome against the live backend: 11 Playwright flows (quick add, editor validate/create/edit, inline backend errors, complete, archive/restore, keyboard tabs, Esc), no console errors; 17 vitest unit tests; restart persistence checked. Rust shell (tray, shortcut, sidecar lifecycle, blur-close) written against verified crate APIs but **not yet compiled** — needs the WebKit apt packages here or a Windows build |
| Phase 1 backend | done 2026-10-26 | SQLAlchemy models + Alembic migration, task service (CRUD, views, disambiguation), settings + keyring, token auth, WS hub; 32 pytest green; curl smoke on 127.0.0.1 verified |
| Scaffold | done 2026-10-26 | uv backend (fastapi 0.162, google-genai 2.33, pvporcupine 4.0.3, sqlalchemy 2.1.6), Tauri 2.12 + React 19 + Tailwind 4 + Framer Motion 14, pytest + vitest green |
