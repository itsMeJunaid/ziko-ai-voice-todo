import { describe, expect, it } from "vitest";
import { dateKey, formatDue, greeting, shiftWallTime, toInputValue, wallDiffMinutes } from "../lib/time";

const TZ = "Asia/Karachi"; // UTC+5, no DST

describe("time helpers", () => {
  it("converts UTC ISO to wall time in the user's zone", () => {
    expect(toInputValue("2026-10-27T05:00:00Z", TZ)).toBe("2026-10-27T10:00");
    expect(toInputValue("2026-10-26T19:30:00Z", TZ)).toBe("2026-10-27T00:30"); // crosses local midnight
    expect(toInputValue(null, TZ)).toBe("");
  });

  it("does wall-clock arithmetic across day boundaries", () => {
    expect(shiftWallTime("2026-10-27T00:10", -15)).toBe("2026-10-26T23:55");
    expect(wallDiffMinutes("2026-10-27T09:45", "2026-10-27T10:00")).toBe(15);
  });

  it("labels due dates relative to the local day", () => {
    const now = new Date("2026-10-26T17:30:00Z"); // 22:30 local
    expect(dateKey(now, TZ)).toBe("2026-10-26");
    expect(formatDue("2026-10-26T19:30:00Z", TZ, now)).toMatch(/^Tomorrow /); // 00:30 local next day
    expect(formatDue("2026-10-26T18:00:00Z", TZ, now)).not.toMatch(/Tomorrow|Yesterday/);
    expect(formatDue("2026-10-25T10:00:00Z", TZ, now)).toMatch(/^Yesterday /);
  });

  it("greets by local hour", () => {
    expect(greeting(new Date("2026-10-26T04:00:00Z"), TZ)).toBe("Good morning"); // 09:00
    expect(greeting(new Date("2026-10-26T10:00:00Z"), TZ)).toBe("Good afternoon"); // 15:00
    expect(greeting(new Date("2026-10-26T17:30:00Z"), TZ)).toBe("Good evening"); // 22:30
  });
});
