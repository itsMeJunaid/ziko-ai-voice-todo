import { useEffect, useRef, useState } from "react";
import type { VoiceState } from "../types";

export type PetEvent = "blink" | "glance" | "doodle" | "hop" | null;

const EVENT_MS: Record<Exclude<PetEvent, null>, number> = { blink: 200, glance: 1200, doodle: 1400, hop: 650 };
const SLEEP_AFTER_MS = 3 * 60_000;

/**
 * Ziko's pet: a little robot with its to-do notebook and pencil. Monochrome so it sits on any wallpaper.
 * Motion is event-based, not looping: between short moves nothing animates, so an idle pet costs ~0% CPU
 * (looping CSS animations cost ~25% here with the GPU renderer off — measured, see index.css).
 */
export function Pet({ state = "idle", event = null, asleep = false, size, look }: {
  state?: VoiceState;
  event?: PetEvent;
  asleep?: boolean;
  size?: number;
  /** Eye offset toward the mouse (hooks/useCursorLook). */
  look?: { x: number; y: number };
}) {
  const cls = ["pet", `pet-${state}`, event ? `pet-ev-${event}` : "", asleep && state === "idle" ? "pet-asleep" : ""].join(" ");
  return (
    <svg viewBox="0 0 64 64" className={cls} width={size} height={size} aria-hidden focusable="false">
      <ellipse className="pet-shadow" cx="32" cy="60" rx="15" ry="2.6" />
      <g className="pet-body">
        <g className="pet-antenna">
          <line className="pet-stem-edge" x1="32" y1="15" x2="32" y2="8.5" />
          <line className="pet-stem" x1="32" y1="15" x2="32" y2="8.5" />
          <circle className="pet-bulb" cx="32" cy="7" r="2.9" />
        </g>
        <rect className="pet-ear" x="9" y="26" width="4.5" height="11" rx="2.2" />
        <rect className="pet-ear" x="50.5" y="26" width="4.5" height="11" rx="2.2" />
        <rect className="pet-head" x="13" y="15" width="38" height="32" rx="12" />
        <rect className="pet-face" x="18" y="20.5" width="28" height="18.5" rx="8" />
        {/* outer layer follows the mouse; the inner one keeps its own poses (glance, look at the notebook) */}
        <g className="pet-look" style={look ? { transform: `translate(${look.x}px, ${look.y}px)` } : undefined}>
          <g className="pet-eyes">
            <rect className="pet-eye" x="23.6" y="25.8" width="4.8" height="7.4" rx="2.4" />
            <rect className="pet-eye" x="35.6" y="25.8" width="4.8" height="7.4" rx="2.4" />
          </g>
        </g>
        <path className="pet-mouth" d="M28.6 42.6 q3.4 2.6 6.8 0" />
        <text className="pet-zzz" x="47" y="13">z</text>
        <g className="pet-book">
          <rect className="pet-page" x="38.5" y="37.5" width="16" height="19" rx="2.6" />
          <rect className="pet-check pet-done" x="41.2" y="41.4" width="3" height="3" rx="0.8" />
          <line className="pet-line" x1="46" y1="42.9" x2="51.8" y2="42.9" />
          <rect className="pet-check" x="41.2" y="46.4" width="3" height="3" rx="0.8" />
          <line className="pet-line" x1="46" y1="47.9" x2="51.2" y2="47.9" />
          <rect className="pet-check" x="41.2" y="51.4" width="3" height="3" rx="0.8" />
          <line className="pet-line" x1="46" y1="52.9" x2="50" y2="52.9" />
        </g>
        {/* placed by attribute (SVG units); CSS only adds the writing wiggle around the pencil's back end */}
        <g transform="translate(31 58) rotate(-50)">
          <g className="pet-pencil">
            <rect x="0" y="-1.3" width="12" height="2.6" rx="0.6" className="pet-pencil-body" />
            <path d="M12 -1.3 L15.2 0 L12 1.3 Z" className="pet-pencil-tip" />
          </g>
        </g>
      </g>
    </svg>
  );
}

/**
 * Picks the pet's occasional moves: mostly blinks, sometimes a glance, a doodle or a hop, every 6–12 s, and
 * nothing while the window is hidden. Falls asleep after 3 min without attention. `poke()` = attention.
 */
export function usePetLife(active: boolean): { event: PetEvent; asleep: boolean; poke: (e?: PetEvent) => void } {
  const [event, setEvent] = useState<PetEvent>(null);
  const [asleep, setAsleep] = useState(false);
  const lastPoke = useRef(Date.now());
  const clearTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const play = (e: Exclude<PetEvent, null>) => {
    clearTimeout(clearTimer.current);
    setEvent(e);
    clearTimer.current = setTimeout(() => setEvent(null), EVENT_MS[e]);
  };

  const poke = (e: PetEvent = "hop") => {
    lastPoke.current = Date.now();
    setAsleep(false);
    if (e) play(e);
  };

  useEffect(() => {
    if (active) poke(null);
  }, [active]);

  useEffect(() => {
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let t: ReturnType<typeof setTimeout>;
    const tick = () => {
      t = setTimeout(tick, 6000 + Math.random() * 6000);
      if (document.hidden || active) return;
      if (Date.now() - lastPoke.current > SLEEP_AFTER_MS) return setAsleep(true);
      const r = Math.random();
      play(reduce || r < 0.6 ? "blink" : r < 0.78 ? "glance" : r < 0.92 ? "doodle" : "hop");
    };
    t = setTimeout(tick, 2500);
    return () => clearTimeout(t);
  }, [active]);

  useEffect(() => () => clearTimeout(clearTimer.current), []);
  return { event, asleep, poke };
}
