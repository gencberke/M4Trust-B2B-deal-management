import type { ApiErrorEnvelope, ApiErrorKind } from "../types/api";

const API_BASE_PATH = "/api";
const CSRF_COOKIE_NAME = "m4t_csrf";
const CSRF_HEADER_NAME = "X-CSRF-Token";
const ACTING_ENTITY_HEADER_NAME = "X-Acting-Entity-ID";

const GENERIC_MESSAGES: Record<ApiErrorKind, string> = {
  session_required: "Bu işlem için yeniden giriş yapmanız gerekiyor.",
  permission_denied: "Bu işlemi gerçekleştirme yetkiniz bulunmuyor.",
  conflict: "İşlem güncel durumla çakıştı. Verileri yenileyip tekrar deneyin.",
  validation: "Gönderilen bilgiler doğrulanamadı. Alanları kontrol edin.",
  not_found: "İstenen kayıt bulunamadı.",
  server: "Sunucuda beklenmeyen bir hata oluştu.",
  network: "Sunucuya ulaşılamadı. Bağlantınızı kontrol edip tekrar deneyin.",
  invalid_response: "Sunucudan güvenli biçimde işlenemeyen bir yanıt alındı.",
  unknown: "İstek tamamlanamadı. Lütfen tekrar deneyin.",
};

export class ApiClientError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly code: string;
  readonly requestId: string | null;
  readonly detail: Record<string, unknown> | null;
  readonly userMessage: string;

  constructor(options: {
    kind: ApiErrorKind;
    status?: number | null;
    code?: string;
    requestId?: string | null;
    detail?: Record<string, unknown> | null;
    userMessage?: string;
  }) {
    const userMessage = options.userMessage ?? GENERIC_MESSAGES[options.kind];
    super(userMessage);
    this.name = "ApiClientError";
    this.kind = options.kind;
    this.status = options.status ?? null;
    this.code = options.code ?? "REQUEST_FAILED";
    this.requestId = options.requestId ?? null;
    this.detail = options.detail ?? null;
    this.userMessage = userMessage;
  }
}

export interface ApiRequestOptions extends Omit<RequestInit, "body"> {
  body?: BodyInit | Record<string, unknown> | null;
  csrf?: boolean;
  redirectOnError?: boolean;
}

type NavigationErrorHandler = (error: ApiClientError) => void;

let actingEntityId: string | null = null;
let navigationErrorHandler: NavigationErrorHandler | null = null;

export function setApiActingEntityId(entityId: string | null): void {
  actingEntityId = entityId;
}

export function setApiNavigationErrorHandler(handler: NavigationErrorHandler | null): void {
  navigationErrorHandler = handler;
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }

  const prefix = `${encodeURIComponent(name)}=`;
  for (const part of document.cookie.split(";")) {
    const trimmed = part.trim();
    if (trimmed.startsWith(prefix)) {
      return decodeURIComponent(trimmed.slice(prefix.length));
    }
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseApiErrorEnvelope(value: unknown): ApiErrorEnvelope | null {
  if (!isRecord(value)) {
    return null;
  }
  if (
    typeof value.code !== "string" ||
    typeof value.message !== "string" ||
    !(typeof value.request_id === "string" || value.request_id === null)
  ) {
    return null;
  }
  if (value.detail !== undefined && !isRecord(value.detail)) {
    return null;
  }
  return {
    code: value.code,
    message: value.message,
    request_id: value.request_id,
    detail: value.detail,
  };
}

function kindForStatus(status: number): ApiErrorKind {
  if (status === 401) return "session_required";
  if (status === 403) return "permission_denied";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 422) return "validation";
  if (status >= 500) return "server";
  return "unknown";
}

function notifyNavigation(error: ApiClientError, enabled: boolean): void {
  if (
    enabled &&
    navigationErrorHandler &&
    (error.kind === "session_required" ||
      error.kind === "permission_denied" ||
      error.kind === "conflict")
  ) {
    navigationErrorHandler(error);
  }
}

function prepareHeaders(options: ApiRequestOptions): Headers {
  const headers = new Headers(options.headers);
  const isStructuredBody =
    options.body !== undefined &&
    options.body !== null &&
    !(options.body instanceof FormData) &&
    !(options.body instanceof URLSearchParams) &&
    !(options.body instanceof Blob) &&
    typeof options.body !== "string";

  if (isStructuredBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (actingEntityId) {
    headers.set(ACTING_ENTITY_HEADER_NAME, actingEntityId);
  }
  if (options.csrf) {
    const csrfToken = readCookie(CSRF_COOKIE_NAME);
    if (!csrfToken) {
      throw new ApiClientError({
        kind: "permission_denied",
        code: "CSRF_COOKIE_MISSING",
        userMessage: "Güvenlik doğrulaması bulunamadı. Yeniden giriş yapın.",
      });
    }
    headers.set(CSRF_HEADER_NAME, csrfToken);
  }
  return headers;
}

function serializeBody(body: ApiRequestOptions["body"]): BodyInit | null | undefined {
  if (body === undefined || body === null) {
    return body;
  }
  if (
    body instanceof FormData ||
    body instanceof URLSearchParams ||
    body instanceof Blob ||
    typeof body === "string"
  ) {
    return body;
  }
  return JSON.stringify(body);
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new ApiClientError({
      kind: "invalid_response",
      status: response.status,
      code: "INVALID_JSON_RESPONSE",
    });
  }
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const redirectOnError = options.redirectOnError ?? true;
  let headers: Headers;

  try {
    headers = prepareHeaders(options);
  } catch (error) {
    const clientError = toApiClientError(error);
    notifyNavigation(clientError, redirectOnError);
    throw clientError;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_PATH}${path}`, {
      ...options,
      body: serializeBody(options.body),
      credentials: "include",
      headers,
    });
  } catch {
    const error = new ApiClientError({ kind: "network", code: "NETWORK_ERROR" });
    notifyNavigation(error, redirectOnError);
    throw error;
  }

  let payload: unknown;
  try {
    payload = await parseResponseBody(response);
  } catch (error) {
    const parsedError = toApiClientError(error);
    const clientError =
      parsedError.kind === "invalid_response" && !response.ok
        ? new ApiClientError({
            kind: kindForStatus(response.status),
            status: response.status,
            code: `HTTP_${response.status}`,
            requestId: response.headers.get("X-Request-ID"),
          })
        : parsedError;
    notifyNavigation(clientError, redirectOnError);
    throw clientError;
  }

  if (!response.ok) {
    const envelope = parseApiErrorEnvelope(payload);
    const kind = kindForStatus(response.status);
    const error = new ApiClientError({
      kind,
      status: response.status,
      code: envelope?.code ?? `HTTP_${response.status}`,
      requestId: envelope?.request_id ?? response.headers.get("X-Request-ID"),
      detail: envelope?.detail ?? null,
      userMessage: envelope?.message ?? GENERIC_MESSAGES[kind],
    });
    notifyNavigation(error, redirectOnError);
    throw error;
  }

  return payload as T;
}

export function toApiClientError(error: unknown): ApiClientError {
  return error instanceof ApiClientError
    ? error
    : new ApiClientError({ kind: "unknown", code: "UNEXPECTED_CLIENT_ERROR" });
}

export function resetApiClientForTests(): void {
  actingEntityId = null;
  navigationErrorHandler = null;
}
