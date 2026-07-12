import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetApiClientForTests } from "./client";
import { listReviews, submitReviewAction } from "./reviews";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api/reviews", () => {
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

  it("listReviews case+actions dizisini parse eder, CSRF göndermez", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([
        {
          case: { id: "rc-1", transaction_id: "tx-1", phase: "pre_ratification", source_type: "validator", source_id: null, reason_code: "VALIDATOR_NEEDS_REVIEW", title: "İnceleme", description: "d", severity: "blocking", status: "open", assigned_to_user_id: null, opened_by_actor_type: "system", opened_by_user_id: null, resolved_by_user_id: null, resolution_code: null, resolution_note: null, created_at: "2026-07-12T00:00:00Z", resolved_at: null },
          actions: [],
        },
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const rows = await listReviews("tx-1");
    expect(rows[0].case.severity).toBe("blocking");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/transactions/tx-1/reviews");
    const headers = (fetchMock.mock.calls[0]?.[1] as RequestInit).headers as Headers;
    expect(headers.get("X-CSRF-Token")).toBeNull();
  });

  it("boş liste döndürür", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([])));
    expect(await listReviews("tx-1")).toEqual([]);
  });

  it("submitReviewAction CSRF header'ı ile POST eder", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ id: "a-1", review_case_id: "rc-1", actor_user_id: "u-1", acting_entity_id: null, action: "comment", payload: { comment: "not" }, created_at: "2026-07-12T00:00:00Z" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await submitReviewAction("rc-1", { action: "comment", comment: "not" });
    expect(result.action).toBe("comment");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/reviews/rc-1/actions");
    expect(init.method).toBe("POST");
    expect((init.headers as Headers).get("X-CSRF-Token")).toBe("csrf-token-123");
  });

  it("403/409 kodlarını ApiClientError olarak yansıtır", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ code: "REVIEW_ACTION_FORBIDDEN", message: "Yetki yok.", request_id: "r1" }, 403),
      ),
    );
    await expect(submitReviewAction("rc-1", { action: "resolve_continue" })).rejects.toMatchObject({
      kind: "permission_denied",
      code: "REVIEW_ACTION_FORBIDDEN",
    });

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ code: "REVIEW_CASE_CLOSED", message: "Kapalı.", request_id: "r2" }, 409),
      ),
    );
    await expect(submitReviewAction("rc-1", { action: "comment", comment: "x" })).rejects.toMatchObject({
      kind: "conflict",
      code: "REVIEW_CASE_CLOSED",
    });
  });
});
