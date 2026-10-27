import { describe, expect, it } from "vitest";
import { emptyForm, formFromTask, reminderValue, toCreate, toPatch, validate } from "../lib/editor";
import type { Task } from "../types";

const TZ = "Asia/Karachi";
const task = (over: Partial<Task> = {}): Task => ({
  id: "1", title: "Present", description: null, status: "pending", priority: "medium",
  due_at: "2026-10-27T05:00:00Z", reminder_at: "2026-10-27T04:45:00Z", timezone: TZ,
  created_at: "", updated_at: "", completed_at: null, archived_at: null, source: "ui", is_overdue: false, ...over,
});

describe("task editor logic", () => {
  it("recognises a preset reminder offset when editing", () => {
    const f = formFromTask(task(), TZ);
    expect(f.due).toBe("2026-10-27T10:00");
    expect(f.reminder).toBe("15");
    expect(reminderValue(f)).toBe("2026-10-27T09:45");
  });

  it("falls back to a custom reminder for non-preset offsets or no deadline", () => {
    expect(formFromTask(task({ reminder_at: "2026-10-27T04:53:00Z" }), TZ).reminder).toBe("custom");
    const f = formFromTask(task({ due_at: null }), TZ);
    expect(f.reminder).toBe("custom");
    expect(f.reminderCustom).toBe("2026-10-27T09:45");
  });

  it("validates like the backend", () => {
    expect(validate(emptyForm(""))).toMatch(/title/);
    expect(validate({ ...emptyForm("x"), reminder: "15" })).toMatch(/due time/);
    expect(validate({ ...emptyForm("x"), due: "2026-10-27T10:00", reminder: "custom", reminderCustom: "2026-10-27T11:00" })).toMatch(/after/);
    expect(validate({ ...emptyForm("x"), due: "2026-10-27T10:00", reminder: "15" })).toBeNull();
  });

  it("creates with naive wall times and trimmed text", () => {
    expect(toCreate({ ...emptyForm("  Call mum "), due: "2026-10-27T10:00", reminder: "60", description: "  " })).toEqual({
      title: "Call mum", description: null, priority: "medium", due_at: "2026-10-27T10:00", reminder_at: "2026-10-27T09:00",
    });
  });

  it("patches only changed fields and never re-sends an untouched reminder", () => {
    const initial = formFromTask(task(), TZ);
    expect(toPatch(initial, { ...initial, title: "Present v2" })).toEqual({ title: "Present v2" });
    expect(toPatch(initial, initial)).toEqual({});
    // moving the deadline moves a relative reminder with it
    expect(toPatch(initial, { ...initial, due: "2026-10-28T10:00" })).toEqual({
      due_at: "2026-10-28T10:00", reminder_at: "2026-10-28T09:45",
    });
    expect(toPatch(initial, { ...initial, reminder: "none" })).toEqual({ reminder_at: null });
  });
});
