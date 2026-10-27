import { describe, expect, it } from "vitest";
import { describeGlass, osEffect, resolveGlass } from "../lib/glass";
import type { GlassSupport } from "../lib/glass";

const linux: GlassSupport = { os: "linux", compositor: true };
const linuxNoComp: GlassSupport = { os: "linux", compositor: false };
const win11: GlassSupport = { os: "windows", compositor: true, win11: true };
const win10: GlassSupport = { os: "windows", compositor: true, win11: false };

describe("glass mode resolution", () => {
  it("auto picks frosted wherever transparency works", () => {
    expect(resolveGlass("auto", linux)).toBe("frosted");
    expect(resolveGlass("auto", win11)).toBe("frosted");
  });

  it("never renders transparency without a compositor (it would show black)", () => {
    for (const p of ["auto", "frosted", "clear", "solid"] as const) expect(resolveGlass(p, linuxNoComp)).toBe("solid");
    expect(describeGlass("clear", linuxNoComp)).toMatch(/No compositor/);
  });

  it("respects an explicit choice", () => {
    expect(resolveGlass("clear", linux)).toBe("clear");
    expect(resolveGlass("solid", win11)).toBe("solid");
  });

  it("uses OS blur only for frosted on Windows: Mica on 11, Acrylic on 10", () => {
    expect(osEffect("frosted", win11)).toBe("mica");
    expect(osEffect("frosted", win10)).toBe("acrylic");
    expect(osEffect("clear", win11)).toBeNull();
    expect(osEffect("frosted", linux)).toBeNull(); // Linux: CSS tint, no blur API
  });
});
