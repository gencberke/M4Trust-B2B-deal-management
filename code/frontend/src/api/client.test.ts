import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiClientError,
  apiRequest,
  resetApiClientForTests,
  setApiActingEntityId,
  setApiNavigationErrorHandler,
} from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("apiRequest", () => {
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

  it("bütün isteklerde cookie credentials gönderir", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest<{ ok: boolean }>("/auth/me");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/me",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("CSRF isteyen mutation'a cookie değerini ve acting entity header'ını ekler", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "entity-1" }, 201));
    vi.stubGlobal("fetch", fetchMock);
    setApiActingEntityId("entity-1");

    await apiRequest("/entities", {
      method: "POST",
      csrf: true,
      body: { legal_name: "Örnek A.Ş." },
    });

    const requestInit = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = requestInit.headers as Headers;
    expect(headers.get("X-CSRF-Token")).toBe("csrf-token-123");
    expect(headers.get("X-Acting-Entity-ID")).toBe("entity-1");
    expect(requestInit.credentials).toBe("include");
  });

  it.each([
    [401, "session_required"],
    [403, "permission_denied"],
    [409, "conflict"],
  ] as const)("%i statusunu %s akışına eşler", async (status, expectedKind) => {
    const handler = vi.fn();
    setApiNavigationErrorHandler(handler);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          { code: "SAFE_CODE", message: "Güvenli mesaj", request_id: "req-1" },
          status,
        ),
      ),
    );

    await expect(apiRequest("/protected")).rejects.toMatchObject({
      kind: expectedKind,
      code: "SAFE_CODE",
      requestId: "req-1",
    });
    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ kind: expectedKind }),
    );
  });

  it("standart olmayan hata gövdesini kullanıcıya doğrudan yansıtmaz", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "ham backend detayı" }, 403)),
    );

    let caught: unknown;
    try {
      await apiRequest("/protected", { redirectOnError: false });
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(ApiClientError);
    expect((caught as ApiClientError).userMessage).not.toContain("ham backend detayı");
    expect((caught as ApiClientError).kind).toBe("permission_denied");
  });

  it("geçiş dönemi FastAPI conflict zarfındaki güvenli kodu korur", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            detail: {
              code: "POLICY_CONTRACT_CONFLICT",
              message: "Sözleşmesel kanıt şartı korunmalıdır.",
              conflicts: ["CONTRACT_REQUIRES_VIDEO"],
            },
          },
          409,
        ),
      ),
    );

    await expect(
      apiRequest("/transactions/tx/tracking-policy", { redirectOnError: false }),
    ).rejects.toMatchObject({
      kind: "conflict",
      code: "POLICY_CONTRACT_CONFLICT",
      detail: { conflicts: ["CONTRACT_REQUIRES_VIDEO"] },
    });
  });

  it("geçersiz JSON içeren 401 yanıtını yine session-required akışına eşler", async () => {
    const handler = vi.fn();
    setApiNavigationErrorHandler(handler);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("not-json", { status: 401 })),
    );

    await expect(apiRequest("/broken-auth")).rejects.toMatchObject({
      kind: "session_required",
      code: "HTTP_401",
    });
    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "session_required" }),
    );
  });

  it("başarılı fakat geçersiz JSON yanıtını güvenli generic hataya dönüştürür", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("not-json", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiRequest("/broken", { redirectOnError: false })).rejects.toMatchObject({
      kind: "invalid_response",
      code: "INVALID_JSON_RESPONSE",
    });
  });
});
