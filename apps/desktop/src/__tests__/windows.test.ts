import { describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/event", () => ({ emitTo: vi.fn(), listen: vi.fn() }));
vi.mock("@tauri-apps/api/window", () => ({}));

const { placePanel, monitorAt, defaultDotPosition } = await import("../services/windows");

const screen = { x: 0, y: 0, w: 1920, h: 1040 };

describe("panel placement", () => {
  it("opens to the right of the dot when there is room", () => {
    expect(placePanel({ x: 100, y: 100, w: 72, h: 72 }, screen, 420, 640, 8)).toEqual({ x: 180, y: 100 });
  });

  it("flips to the left near the right edge", () => {
    expect(placePanel({ x: 1820, y: 100, w: 72, h: 72 }, screen, 420, 640, 8)).toEqual({ x: 1392, y: 100 });
  });

  it("stays inside the bottom edge", () => {
    expect(placePanel({ x: 100, y: 900, w: 72, h: 72 }, screen, 420, 640, 8).y).toBe(400);
  });

  it("respects a secondary monitor's offset", () => {
    const right = { x: 1920, y: 0, w: 2560, h: 1400 };
    const p = placePanel({ x: 1930, y: 50, w: 72, h: 72 }, right, 420, 640, 8);
    expect(p.x).toBeGreaterThanOrEqual(1920);
  });
});

describe("monitor helpers", () => {
  const m = (x: number, w: number) =>
    ({ position: { x, y: 0 }, size: { width: w, height: 1080 }, scaleFactor: 1.5 }) as never;

  it("finds the monitor under a point and reports off-screen points", () => {
    const mons = [m(0, 1920), m(1920, 1920)];
    expect(monitorAt(mons, 2000, 10)).toBe(mons[1]);
    expect(monitorAt(mons, 4000, 10)).toBeNull(); // display unplugged
  });

  it("places the pet in the bottom-right corner, scaled", () => {
    const corner = Math.round((64 + 12) * 1.5);
    expect(defaultDotPosition(m(0, 1920))).toEqual({ x: 1920 - corner, y: 1080 - corner });
  });

  it("keeps the pet above a bottom taskbar (work area)", () => {
    const withBar = { ...(m(0, 1920) as object), workArea: { position: { x: 0, y: 0 }, size: { width: 1920, height: 1032 } } };
    expect(defaultDotPosition(withBar as never).y).toBe(1032 - Math.round((64 + 12) * 1.5));
  });
});
