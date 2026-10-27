import { useEffect, useRef } from "react";
import { emit, listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import { Menu } from "@tauri-apps/api/menu";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { useDotPosition } from "../hooks/useDotPosition";
import { Pet, usePetLife } from "./Pet";
import { useCursorLook } from "../hooks/useCursorLook";
import { useDotStatus } from "../hooks/useDotStatus";
import { useTheme } from "../lib/theme";
import { isTauri } from "../services/backend";
import { resetDotPosition, showPanel, togglePanel, trackPanelBlurHides } from "../services/windows";

const DRAG_THRESHOLD = 4;

/**
 * The always-on-top floating dot (PRD §3.1), drawn as Ziko's pet: a small robot with its to-do notebook.
 * It mirrors the voice state and plays short idle moves; at rest nothing animates (see Pet.tsx).
 * Click: toggle panel · Drag: move · Double-click: talk to Ziko · Right-click: quick actions.
 */
export function FloatingDot() {
  useDotPosition();
  useTheme(); // keeps data-theme in sync with the panel window
  const state = useRef<ReturnType<typeof usePetLife> | null>(null);
  // PRD §4.3 step 3: on "Hey Ziko" the pet hops and the panel opens.
  const { alerts, voice, startVoice, setMuted } = useDotStatus(() => {
    state.current?.poke("hop");
    if (isTauri()) void showPanel();
  });
  const muted = voice?.muted ?? false;
  const voiceState = voice?.state ?? "idle";
  const life = usePetLife(voiceState !== "idle");
  state.current = life;
  // Eyes follow the mouse unless they're shut or busy with the notebook. The cursor coming close gets a
  // blink, and wakes a napping pet (poke clears sleep).
  const tracking = !muted && !life.asleep && voiceState !== "processing" && life.event !== "doodle";
  const look = useCursorLook(!muted, () => life.poke("blink"));
  const prevAlerts = useRef(alerts);
  useEffect(() => {
    if (alerts > prevAlerts.current) life.poke("hop"); // a reminder fired: get the user's attention
    prevAlerts.current = alerts;
  }, [alerts, life]);
  const press = useRef<{ x: number; y: number; dragging: boolean } | null>(null);

  useEffect(() => {
    if (!isTauri()) return;
    const subs = [
      trackPanelBlurHides(),
      listen("ziko://toggle-panel", () => void togglePanel()),
      listen<boolean>("ziko://mute", (e) => void setMuted(e.payload)), // tray + this menu; the backend owns the mic
    ];
    return () => void subs.forEach((p) => p.then((u) => u(), () => {}));
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    press.current = { x: e.screenX, y: e.screenY, dragging: false };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const p = press.current;
    if (!p || p.dragging) return;
    if (Math.hypot(e.screenX - p.x, e.screenY - p.y) > DRAG_THRESHOLD) {
      p.dragging = true;
      if (isTauri()) void getCurrentWindow().startDragging(); // OS drag; position saved by onMoved
    }
  };

  const onClick = (e: React.MouseEvent) => {
    const wasDrag = press.current?.dragging;
    press.current = null;
    if (wasDrag || e.detail > 1) return; // the 2nd click of a double-click is handled below
    life.poke("hop");
    if (isTauri()) void togglePanel();
  };

  const onDoubleClick = () => {
    if (!isTauri()) return;
    void showPanel();
    void startVoice();
  };

  const onContextMenu = async (e: React.MouseEvent) => {
    e.preventDefault();
    if (!isTauri()) return;
    const menu = await Menu.new({
      items: [
        { id: "open", text: "Open Ziko", action: () => void showPanel() },
        { id: "add", text: "Add task…", action: () => void showPanel().then(() => emit("ziko://add-task")) },
        {
          id: "mute",
          text: muted ? "Unmute microphone" : "Mute microphone",
          action: () => void emit("ziko://mute", !muted),
        },
        { id: "reset", text: "Reset dot position", action: () => void resetDotPosition() },
        { item: "Separator" },
        { id: "quit", text: "Quit Ziko", action: () => void invoke("quit_app") },
      ],
    });
    await menu.popup();
  };

  return (
    <div className="grid h-full w-full place-items-center">
      <button
        type="button"
        aria-label={`Ziko${alerts ? `, ${alerts} reminder${alerts > 1 ? "s" : ""} waiting` : ""}${muted ? " (microphone muted)" : ""}. Click to open, drag to move.`}
        title="Ziko — click to open · drag to move · right-click for options"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onClick={onClick}
        onDoubleClick={onDoubleClick}
        onContextMenu={onContextMenu}
        onPointerEnter={() => life.poke(null)}
        className="pet-btn cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <Pet state={voiceState} event={life.event} asleep={life.asleep} look={tracking ? look : undefined} />
        {alerts > 0 && (
          <span aria-hidden className="pet-badge">
            {alerts > 9 ? "9+" : alerts}
          </span>
        )}
      </button>
    </div>
  );
}
