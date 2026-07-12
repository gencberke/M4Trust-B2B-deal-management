import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, resetApiClientForTests } from "./client";
import {
  createTransaction,
  getTransaction,
  listTransactions,
  retryExtraction,
} from "./transactions";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api/transactions", () => {
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

  it("createTransaction multipart'ı manuel Content-Type olmadan, CSRF header ile gönderir", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        id: "tx-1",
        lifecycle_version: "account_v2",
        own_role: "buyer",
        acting_entity_id: "ent-1",
        invitation: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const form = new FormData();
    form.append("file", new Blob(["x"]), "c.md");
    form.append("acting_entity_id", "ent-1");
    form.append("own_role", "buyer");

    const result = await createTransaction(form);
    expect(result.id).toBe("tx-1");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/transactions");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.body).toBeInstanceOf(FormData);
    const headers = init.headers as Headers;
    expect(headers.get("X-CSRF-Token")).toBe("csrf-token-123");
    expect(headers.get("Content-Type")).toBeNull();
  });

  it("listTransactions tipli diziyi parse eder, CSRF göndermez", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([
        { id: "tx-1", state: "active", created_at: "2026-07-12T00:00:00Z", buyer_name: "A", seller_name: null },
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const rows = await listTransactions();
    expect(rows).toHaveLength(1);
    expect(rows[0].state).toBe("active");
    const headers = (fetchMock.mock.calls[0]?.[1] as RequestInit).headers as Headers;
    expect(headers.get("X-CSRF-Token")).toBeNull();
  });

  it("getTransaction detay zarfını parse eder", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        id: "tx-1",
        state: "awaiting_approval",
        created_at: "2026-07-12T00:00:00Z",
        lifecycle_version: "account_v2",
        canonical_state: null,
        extraction: null,
        validator: { status: "PASS", findings: [] },
        events: [],
        payment: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const detail = await getTransaction("tx-1");
    expect(detail.validator?.status).toBe("PASS");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/transactions/tx-1");
  });

  it("retryExtraction projeksiyonu döner ve CSRF gönderir", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        transaction_id: "tx-1",
        job_id: "job-1",
        job_status: "queued",
        attempt_count: 2,
        transaction_state: "extracting",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await retryExtraction("tx-1");
    expect(result.job_status).toBe("queued");
    const headers = (fetchMock.mock.calls[0]?.[1] as RequestInit).headers as Headers;
    expect(headers.get("X-CSRF-Token")).toBe("csrf-token-123");
  });

  it("hata zarfını ApiClientError.code'a eşler", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          { code: "EXTRACTION_RETRY_IN_PROGRESS", message: "Zaten sürüyor.", request_id: "req-9" },
          409,
        ),
      ),
    );

    await expect(retryExtraction("tx-1")).rejects.toMatchObject({
      kind: "conflict",
      code: "EXTRACTION_RETRY_IN_PROGRESS",
    });
  });

  it("⚠️str 403 detayını ham göstermez, HTTP_403 koduna düşer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "Bu işlemde erişiminiz yok." }, 403)),
    );

    let caught: unknown;
    try {
      await getTransaction("tx-1");
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(ApiClientError);
    expect((caught as ApiClientError).kind).toBe("permission_denied");
    expect((caught as ApiClientError).code).toBe("HTTP_403");
    expect((caught as ApiClientError).userMessage).not.toContain("erişiminiz yok");
  });

  it("401 detay okumasını session_required akışına eşler", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "Kimlik doğrulama gerekli." }, 401)),
    );
    await expect(getTransaction("tx-1")).rejects.toMatchObject({ kind: "session_required" });
  });

  it("geçersiz JSON yanıtını invalid_response'a çevirir", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("not-json", { status: 200, headers: { "Content-Type": "application/json" } }),
      ),
    );
    await expect(listTransactions().catch((e) => Promise.reject(e))).rejects.toMatchObject({
      kind: "invalid_response",
    });
  });
});
