/**
 * Frontend client ↔ real backend. Runs only when ZIKO_IT_URL is set:
 *   ZIKO_IT_URL=http://127.0.0.1:8798 ZIKO_IT_TOKEN=… pnpm test
 */
import { describe, expect, it } from "vitest";
import { Api, ApiError } from "../services/api";

const url = process.env.ZIKO_IT_URL;
const token = process.env.ZIKO_IT_TOKEN ?? "";

describe.skipIf(!url)("Api against a live backend", () => {
  const api = new Api({ base_url: url!, token });

  it("runs the panel's CRUD flow end to end", async () => {
    const t = await api.createTask({ title: "Integration task", due_at: "2099-01-01T10:00", reminder_at: "2099-01-01T09:45" });
    expect(t.status).toBe("pending");
    expect((await api.listTasks("upcoming")).items.map((x) => x.id)).toContain(t.id);

    const u = await api.updateTask(t.id, { priority: "high" });
    expect(u.priority).toBe("high");
    expect(u.reminder_at).toBe(t.reminder_at);

    expect((await api.completeTask(t.id)).status).toBe("completed");
    expect((await api.listTasks("completed")).items.map((x) => x.id)).toContain(t.id);
    expect((await api.reopenTask(t.id)).status).toBe("pending");
    expect((await api.archiveTask(t.id)).status).toBe("archived");
    expect((await api.listTasks("archived")).items.map((x) => x.id)).toContain(t.id);
  });

  it("surfaces backend validation as ApiError", async () => {
    await expect(api.createTask({ title: "x", due_at: "2099-01-01T10:00", reminder_at: "2099-01-01T11:00" })).rejects.toMatchObject({
      code: "validation_error",
    });
  });

  it("rejects a wrong token", async () => {
    const bad = new Api({ base_url: url!, token: "wrong" });
    await expect(bad.listTasks("today")).rejects.toBeInstanceOf(ApiError);
  });

  it("reports an unreachable backend as offline", async () => {
    const dead = new Api({ base_url: "http://127.0.0.1:1", token });
    await expect(dead.listTasks("today")).rejects.toMatchObject({ code: "offline" });
  });
});
