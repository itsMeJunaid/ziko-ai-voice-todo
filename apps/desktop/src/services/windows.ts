import { emitTo, listen } from "@tauri-apps/api/event";
import { availableMonitors, getCurrentWindow, PhysicalPosition, primaryMonitor, Window } from "@tauri-apps/api/window";
import type { Monitor } from "@tauri-apps/api/window";

export const DOT_WINDOW = 64; // logical px, matches tauri.conf.json
const PANEL_W = 420; // fallback if the window size can't be read
const PANEL_H = 640;
const GAP = 8;
const EDGE = 12;

type Rect = { x: number; y: number; w: number; h: number };

/** Monitor containing a physical point, or null if the point is off every screen. */
export function monitorAt(monitors: Monitor[], x: number, y: number): Monitor | null {
  return (
    monitors.find(
      (m) => x >= m.position.x && x < m.position.x + m.size.width && y >= m.position.y && y < m.position.y + m.size.height,
    ) ?? null
  );
}

/**
 * Pure placement: put the panel beside the dot on the side with room, clamped to the monitor's
 * work area (PRD §3.2 "reposition itself within the visible screen bounds").
 */
export function placePanel(dot: Rect, screen: Rect, panelW: number, panelH: number, gap: number): { x: number; y: number } {
  let x = dot.x + dot.w + gap;
  if (x + panelW > screen.x + screen.w) x = dot.x - panelW - gap;
  let y = dot.y;
  if (y + panelH > screen.y + screen.h) y = screen.y + screen.h - panelH;
  x = Math.min(Math.max(screen.x, x), screen.x + screen.w - panelW);
  y = Math.max(screen.y, y);
  return { x: Math.round(x), y: Math.round(y) };
}

/** Default pet position: the bottom-right corner of the work area (above a bottom taskbar or dock). */
export function defaultDotPosition(m: Monitor): { x: number; y: number } {
  const s = m.scaleFactor;
  const area = m.workArea ?? { position: m.position, size: m.size };
  return {
    x: Math.round(area.position.x + area.size.width - (DOT_WINDOW + EDGE) * s),
    y: Math.round(area.position.y + area.size.height - (DOT_WINDOW + EDGE) * s),
  };
}

// The panel hides itself on blur. A click on the dot blurs the panel *before* the dot's click handler
// runs, so the dot must know "the panel just closed because of me" to avoid reopening it immediately.
let lastBlurHide = 0;
export async function trackPanelBlurHides(): Promise<() => void> {
  return listen("panel://blur-hidden", () => {
    lastBlurHide = Date.now();
  });
}

export async function togglePanel(): Promise<void> {
  const panel = await Window.getByLabel("panel");
  if (!panel) return;
  if (await panel.isVisible()) {
    await panel.hide();
    return;
  }
  if (Date.now() - lastBlurHide < 350) return; // this click is what closed it
  await showPanel(panel);
}

export async function showPanel(panel?: Window | null): Promise<void> {
  panel ??= await Window.getByLabel("panel");
  if (!panel) return;
  const dot = await Window.getByLabel("dot");
  let target: PhysicalPosition | null = null;
  if (dot) {
    // The panel is resizable, so place it by its real current size.
    const [pos, scale, monitors, size] = await Promise.all([
      dot.outerPosition(),
      dot.scaleFactor(),
      availableMonitors(),
      panel.outerSize().catch(() => null),
    ]);
    const m = monitorAt(monitors, pos.x, pos.y) ?? monitors[0];
    if (m) {
      const area = m.workArea ?? { position: m.position, size: m.size };
      const p = placePanel(
        { x: pos.x, y: pos.y, w: DOT_WINDOW * scale, h: DOT_WINDOW * scale },
        { x: area.position.x, y: area.position.y, w: area.size.width, h: area.size.height },
        size?.width ?? PANEL_W * scale,
        size?.height ?? PANEL_H * scale,
        GAP * scale,
      );
      target = new PhysicalPosition(p.x, p.y);
      await panel.setPosition(target);
    }
  }
  await panel.show();
  // X11 window managers (GNOME/XWayland) ignore a move made while the window is hidden: repeat it once mapped.
  if (target) await panel.setPosition(target);
  await panel.setFocus();
  await emitTo("panel", "panel://shown");
}

/** Called from inside the panel window. */
export async function hidePanel(reason: "blur" | "user" = "user"): Promise<void> {
  await getCurrentWindow().hide();
  if (reason === "blur") await emitTo("dot", "panel://blur-hidden");
}

export async function resetDotPosition(): Promise<void> {
  const m = (await primaryMonitor()) ?? (await availableMonitors())[0];
  if (!m) return;
  const p = defaultDotPosition(m);
  await getCurrentWindow().setPosition(new PhysicalPosition(p.x, p.y));
}
