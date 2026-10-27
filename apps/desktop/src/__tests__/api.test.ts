import { describe, expect, it } from "vitest";
import { ApiError, toApiError } from "../services/api";

describe("API error envelope", () => {
  it("maps the backend envelope", async () => {
    const res = new Response(JSON.stringify({ error: { code: "ambiguous", message: "2 tasks match", details: { candidates: [] } } }), { status: 409 });
    const e = await toApiError(res);
    expect(e).toBeInstanceOf(ApiError);
    expect([e.status, e.code, e.message]).toEqual([409, "ambiguous", "2 tasks match"]);
  });

  it("survives non-JSON bodies", async () => {
    const e = await toApiError(new Response("Bad gateway", { status: 502 }));
    expect([e.code, e.message]).toEqual(["http_error", "Request failed (502)"]);
  });
});
