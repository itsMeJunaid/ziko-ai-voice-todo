import { Pet } from "./Pet";
import type { PetEvent } from "./Pet";
import type { VoiceState } from "../types";

const STATES: VoiceState[] = ["idle", "listening", "processing", "speaking", "muted", "error"];
const EVENTS: PetEvent[] = ["blink", "glance", "doodle", "hop"];

/** Dev-only design sheet (`pnpm dev` → /#/pet-preview): every pet state on dark and light. */
export function PetPreview() {
  const cell = (label: string, node: React.ReactNode) => (
    <figure key={label} className="flex flex-col items-center gap-1.5">
      <div style={{ width: 64, height: 64 }}>{node}</div>
      <figcaption className="text-[10px]" style={{ opacity: 0.7 }}>{label}</figcaption>
    </figure>
  );
  const sheet = (bg: string, fg: string) => (
    <div className="grid grid-cols-6 gap-4 p-5" style={{ background: bg, color: fg }}>
      {STATES.map((s) => cell(s, <Pet state={s} />))}
      {cell("asleep", <Pet asleep />)}
      {EVENTS.map((e) => cell(`ev: ${e}`, <Pet event={e} />))}
      {cell("size 36", <Pet size={36} />)}
      {cell("look left", <Pet look={{ x: -3.5, y: 0 }} />)}
      {cell("look right", <Pet look={{ x: 3.5, y: 0.5 }} />)}
      {cell("look up", <Pet look={{ x: 1, y: -2.5 }} />)}
      {cell("look down", <Pet look={{ x: -1.5, y: 2.5 }} />)}
    </div>
  );
  return (
    <div className="flex flex-col">
      {sheet("#2a2d33", "#ddd")}
      {sheet("#e9e6df", "#333")}
    </div>
  );
}
