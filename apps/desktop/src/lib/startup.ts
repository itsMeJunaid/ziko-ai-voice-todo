import { isTauri } from "../services/backend";

/**
 * OS login item via tauri-plugin-autostart (registered with `--minimized` in lib.rs).
 * Only the installed (production) app manages it: a dev build would point the login entry at a binary under
 * target/ that disappears. When on, it is rewritten every start so it always points at the running install.
 */
export async function setLaunchAtLogin(on: boolean): Promise<void> {
  if (!isTauri() || import.meta.env.DEV) return;
  const { enable, disable, isEnabled } = await import("@tauri-apps/plugin-autostart");
  if (on) await enable();
  else if (await isEnabled()) await disable();
}
