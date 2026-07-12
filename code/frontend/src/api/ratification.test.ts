import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, resetApiClientForTests } from "./client";
import {
  buildRatificationPackage,
  getCurrentRatificationPackage,
  submitRatification,
} from "./ratification";
import { isNoPackageError } from "../pages/transactions/ratification/packageLogic";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api/ratification", () => {
  beforeEach(() => {
    resetApiClientForTests();
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: { cookie: "m4t_csrf=csrf-token-123" },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(globalThis, "document");
  });

  it("current package 404 → isNoPackageError true (hata değil, ön-durum)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ code: "PACKAGE_NOT_FOUND", message: "yok", request_id: "r1" }, 404),
      ),
    );
    let caught: unknown;
    try {
      await getCurrentRatificationPackage("tx-1");
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(ApiClientError);
    expect(isNoPackageError(caught as ApiClientError)).toBe(true);
  });

  it("build 409 readiness kodunu ApiClientError.code'a taşır", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ code: "TRACKING_POLICY_NOT_LOCKED", message: "kilitli değil", request_id: "r2" }, 409),
      ),
    );
    await expect(buildRatificationPackage("tx-1", {})).rejects.toMatchObject({
      kind: "conflict",
      code: "TRACKING_POLICY_NOT_LOCKED",
    });
  });

  it("build CSRF header'ı ile POST eder", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ id: "pkg-1", transaction_id: "tx-1", version: 1, status: "open", package_hash: "abc", canonical_payload: {}, created_at: "t", opened_at: "t", completed_at: null, ratifications: {} }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const pkg = await buildRatificationPackage("tx-1", { funding_schedule_spec: { overrides: [] } });
    expect(pkg.status).toBe("open");
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Headers).get("X-CSRF-Token")).toBe("csrf-token-123");
  });

  it("ratify idempotent replay: funding_triggered=false başarı olarak döner", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          ratification: { id: "rt-1", package_id: "pkg-1", transaction_id: "tx-1", participant_id: "p", user_id: "u", legal_entity_id: "e", participant_role: "buyer", auth_method: "session", approved_at: "t" },
          package_status: "open",
          funding_triggered: false,
        }),
      ),
    );
    const outcome = await submitRatification("pkg-1");
    expect(outcome.funding_triggered).toBe(false);
    expect(outcome.ratification.participant_role).toBe("buyer");
  });

  it("ratify 409 PACKAGE_SUPERSEDED kodunu taşır", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ code: "PACKAGE_SUPERSEDED", message: "yenilendi", request_id: "r3" }, 409),
      ),
    );
    await expect(submitRatification("pkg-1")).rejects.toMatchObject({
      kind: "conflict",
      code: "PACKAGE_SUPERSEDED",
    });
  });
});
