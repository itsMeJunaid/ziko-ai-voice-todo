import { describe, expect, it } from "vitest";
import { addTranscript } from "../lib/voice";

describe("transcript folding", () => {
  it("joins streamed reply chunks and closes them on the final event", () => {
    let t = addTranscript([], { role: "user", text: "add milk", final: true });
    t = addTranscript(t, { role: "assistant", text: "Added ", final: false });
    t = addTranscript(t, { role: "assistant", text: "milk.", final: false });
    t = addTranscript(t, { role: "assistant", text: "", final: true });
    expect(t).toEqual([
      { role: "user", text: "add milk", final: true },
      { role: "assistant", text: "Added milk.", final: true },
    ]);
    t = addTranscript(t, { role: "assistant", text: "Anything else?", final: false });
    expect(t).toHaveLength(3); // a new reply after a closed one starts a new line
  });

  it("ignores an empty close with nothing open and keeps the last 20 lines", () => {
    expect(addTranscript([], { role: "assistant", text: "", final: true })).toEqual([]);
    let t: ReturnType<typeof addTranscript> = [];
    for (let i = 0; i < 25; i++) t = addTranscript(t, { role: "user", text: `q${i}`, final: true });
    expect(t).toHaveLength(20);
    expect(t[0].text).toBe("q5");
  });

  it("streams spoken user words into one line", () => {
    let t = addTranscript([], { role: "user", text: "what's ", final: false });
    t = addTranscript(t, { role: "user", text: "today", final: false });
    expect(t).toEqual([{ role: "user", text: "what's today", final: false }]);
  });
});

import { lookAt } from "../hooks/useCursorLook";

describe("pet eyes follow the cursor", () => {
  it("points toward the cursor and saturates far away", () => {
    expect(lookAt(0, 0)).toEqual({ x: 0, y: 0 });
    expect(lookAt(1000, 0)).toEqual({ x: 3.5, y: 0 }); // far right: eyes at the right edge
    expect(lookAt(0, -1000)).toEqual({ x: 0, y: -2.5 }); // far above
    const near = lookAt(65, 0); // a quarter of the way: a small glance
    expect(near).toEqual({ x: 1, y: 0 }); // whole 0.5 steps only
    expect(lookAt(10, 0)).toEqual({ x: 0, y: 0 }); // cursor on the pet itself: eyes stay centred
  });

  it("keeps the diagonal inside the eye socket", () => {
    const d = lookAt(-800, 800);
    expect(d.x).toBeLessThan(0);
    expect(d.y).toBeGreaterThan(0);
    expect(Math.abs(d.x)).toBeLessThanOrEqual(3.5);
  });
});
