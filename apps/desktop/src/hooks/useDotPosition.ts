import { useEffect } from "react";
import { availableMonitors, getCurrentWindow, PhysicalPosition } from "@tauri-apps/api/window";
import { load } from "@tauri-apps/plugin-store";
import { isTauri } from "../services/backend";
import { monitorAt, resetDotPosition } from "../services/windows";

const STORE = "ziko-ui.json";
const KEY = "dot.position";

/**
 * PRD §3.1 positioning rules: restore the saved position; if it is no longer on any monitor
 * (unplugged display, resolution change) fall back to the default; persist every move (debounced).
 * The dot is only moved automatically when its saved location is invalid.
 */
export function useDotPosition(): void {
  useEffect(() => {
    if (!isTauri()) return;
    const win = getCurrentWindow();
    const unlisten: Array<() => void> = [];
    let timer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;

    (async () => {
      try {
      const store = await load(STORE, { autoSave: true, defaults: {} });
      const saved = await store.get<{ x: number; y: number }>(KEY);
      const monitors = await availableMonitors();
      if (saved && monitorAt(monitors, saved.x + 8, saved.y + 8)) {
        await win.setPosition(new PhysicalPosition(saved.x, saved.y));
      } else {
        await resetDotPosition();
      }

      const revalidate = async () => {
        const pos = await win.outerPosition();
        if (!monitorAt(await availableMonitors(), pos.x + 8, pos.y + 8)) await resetDotPosition();
      };
      if (disposed) return;
      unlisten.push(
        await win.onMoved(({ payload }) => {
          clearTimeout(timer);
          timer = setTimeout(async () => {
            await revalidate();
            await store.set(KEY, { x: payload.x, y: payload.y });
          }, 300);
        }),
        await win.onScaleChanged(() => void revalidate()),
      );
      } catch (e) {
        console.error("dot position unavailable", e); // keep the dot usable where Tauri placed it
      }
    })();

    return () => {
      disposed = true;
      clearTimeout(timer);
      unlisten.forEach((u) => u());
    };
  }, []);
}
