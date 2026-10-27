import { useEffect, useRef, useState } from "react";
import { isTauri } from "../services/backend";

export interface Look {
  x: number; // eye offset in pet units (viewBox 64)
  y: number;
}

const MAX_X = 3.5;
const MAX_Y = 2.5;
const STEP = 0.5; // eyes move in visible steps: most cursor motion changes nothing, so nothing repaints
const FULL_AT = 260; // px of distance at which the eyes reach the edge
const FAST_MS = 100;
const SLOW_MS = 350;
const STILL_AFTER_MS = 2500;
const NEAR = 90; // px: "the cursor came to say hi"

/** Pure: where the eyes point for a cursor at (dx, dy) physical px from the pet's centre. */
export function lookAt(dx: number, dy: number): Look {
  const dist = Math.hypot(dx, dy);
  if (dist < 1) return { x: 0, y: 0 };
  const k = Math.min(1, dist / FULL_AT);
  const r = (v: number) => Math.round(v / STEP) * STEP || 0; // `|| 0`: no -0
  return { x: r((dx / dist) * k * MAX_X), y: r((dy / dist) * k * MAX_Y) };
}

/**
 * The pet's eyes follow the mouse anywhere on screen. The dot window only gets mouse events over itself, so
 * this polls the global cursor position: ~12/s while the cursor moves, ~3/s once it has been still, and not
 * at all while `enabled` is false (asleep, muted, busy poses) or the window is hidden. State only changes when
 * the eyes move by a whole step (no CSS transition: a slide per tick repainted continuously while the mouse
 * moved, ~18% CPU in software rendering), so a still or slowly moving cursor causes no repaints.
 */
export function useCursorLook(enabled: boolean, onNear: () => void): Look {
  const [look, setLook] = useState<Look>({ x: 0, y: 0 });
  const nearRef = useRef(onNear);
  nearRef.current = onNear;

  useEffect(() => {
    if (!enabled || !isTauri()) {
      setLook({ x: 0, y: 0 });
      return;
    }
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    let last = { x: NaN, y: NaN };
    let movedAt = Date.now();
    let wasNear = false;
    let centre: { x: number; y: number } | null = null;
    let centreAt = 0;

    void (async () => {
      const { cursorPosition, getCurrentWindow } = await import("@tauri-apps/api/window");
      const win = getCurrentWindow();
      const tick = async () => {
        if (stop) return;
        try {
          if (!document.hidden) {
            if (!centre || Date.now() - centreAt > 2000) {
              const [pos, size] = await Promise.all([win.outerPosition(), win.outerSize()]);
              centre = { x: pos.x + size.width / 2, y: pos.y + size.height / 2 };
              centreAt = Date.now();
            }
            const c = await cursorPosition();
            if (c.x !== last.x || c.y !== last.y) {
              last = { x: c.x, y: c.y };
              movedAt = Date.now();
              const dx = c.x - centre.x;
              const dy = c.y - centre.y;
              const next = lookAt(dx, dy);
              setLook((prev) => (prev.x === next.x && prev.y === next.y ? prev : next));
              const near = Math.hypot(dx, dy) < NEAR;
              if (near && !wasNear) nearRef.current();
              wasNear = near;
            }
          }
        } catch {
          /* cursor unavailable for a moment (e.g. display change): try again next tick */
        }
        timer = setTimeout(tick, Date.now() - movedAt > STILL_AFTER_MS ? SLOW_MS : FAST_MS);
      };
      void tick();
    })();

    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [enabled]);

  return look;
}
