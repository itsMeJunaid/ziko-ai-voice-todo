import { describe, expect, it } from "vitest";
import { notificationFor } from "../hooks/useDotStatus";
import type { Reminder } from "../types";

const TZ = "Asia/Karachi";
const base: Reminder = {
  id: "r1",
  task_id: "t1",
  task_title: "Call the bank",
  task_due_at: null,
  fire_at: "2026-10-26T18:00:00Z", // 23:00 Karachi
  state: "delivered",
  delivered_at: "2026-10-26T18:00:00Z",
  missed: false,
};

describe("reminder notification text", () => {
  it("uses the task title and says when it is due", () => {
    expect(notificationFor(base, TZ).title).toBe("Call the bank");
    expect(notificationFor(base, TZ).body).toBe("Ziko reminder");
    const due = notificationFor({ ...base, task_due_at: "2026-10-26T18:15:00Z" }, TZ);
    expect(due.body).toMatch(/^Due .*11:15/);
  });

  it("labels a reminder delivered late as missed, with its original time", () => {
    const n = notificationFor({ ...base, state: "missed", missed: true }, TZ);
    expect(n.title).toBe("Missed: Call the bank");
    expect(n.body).toMatch(/^Was set for .*11:00/);
  });
});
