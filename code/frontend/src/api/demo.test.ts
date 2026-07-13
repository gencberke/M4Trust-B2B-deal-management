import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClientError, resetApiClientForTests } from "./client";
import { probeDemoStatus, advanceDemoTransaction } from "./demo";

describe("demo api", () => {
  beforeEach(() =>
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: { cookie: "m4t_csrf=x" },
    }),
  );
  afterEach(() => {
    resetApiClientForTests();
    vi.unstubAllGlobals();
    Reflect.deleteProperty(globalThis, "document");
  });

  it("probe returns status when flag on (200)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ demo_tools_enabled: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    expect(await probeDemoStatus()).toEqual({ demo_tools_enabled: true });
  });

  it("probe returns null on 404 (flag off = demo UI gate)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("", { status: 404 })),
    );
    expect(await probeDemoStatus()).toBeNull();
  });

  it("probe rethrows non-404 errors (e.g. 401)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("", { status: 401 })),
    );
    await expect(probeDemoStatus()).rejects.toBeInstanceOf(ApiClientError);
  });

  it("advance posts target_state with csrf", async () => {
    const f = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ transaction_id: "t", state: "active", lifecycle_version: "account_v2" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", f);
    const result = await advanceDemoTransaction("t", "active");
    expect(result.state).toBe("active");
    const [, init] = f.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ target_state: "active" });
    expect(init.headers.get("X-CSRF-Token")).toBe("x");
  });
});
