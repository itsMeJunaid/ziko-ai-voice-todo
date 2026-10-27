# Ziko desktop app

The Tauri 2 shell (Rust, `src-tauri/`) and the React + TypeScript UI (`src/`): the robot pet window, the task panel,
settings, tray, global shortcut, and the lifecycle of the Python backend sidecar.

```bash
pnpm install
pnpm tauri dev        # run with the backend from ../../backend/.venv
pnpm test             # vitest
pnpm typecheck        # tsc
pnpm e2e              # Playwright UI flows (see e2e/*.cjs for what they need running)
```

Dev-only design sheet of every pet state: `pnpm dev` → <http://localhost:1420/#/pet-preview>.

See the [developer guide](../../docs/DEVELOPMENT.md) for prerequisites, packaging and architecture.
