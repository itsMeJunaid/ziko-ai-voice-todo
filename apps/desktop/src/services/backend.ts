import type { BackendInfo } from "../types";

export const isTauri = (): boolean => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/**
 * Where the backend lives. Inside Tauri the Rust shell owns the process and hands us a random port + token.
 * In a plain browser (`pnpm dev` while `python -m app.main` runs) we fall back to Vite env vars.
 */
export async function getBackendInfo(): Promise<BackendInfo> {
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<BackendInfo>("backend_info");
  }
  const base = import.meta.env.VITE_ZIKO_API ?? "http://127.0.0.1:8765";
  const token = import.meta.env.VITE_ZIKO_TOKEN ?? "dev-token-change-me";
  return {
    base_url: base,
    ws_url: `${base.replace(/^http/, "ws")}/ws/events?token=${encodeURIComponent(token)}`,
    token,
    status: "ready",
  };
}

/** Subscribe to Rust-side backend lifecycle changes. Returns an unsubscribe function. */
export async function onBackendStatus(cb: (info: BackendInfo) => void): Promise<() => void> {
  if (!isTauri()) return () => {};
  const { listen } = await import("@tauri-apps/api/event");
  return listen<BackendInfo>("backend://status", (e) => cb(e.payload));
}
