import type { ApiClientError } from "../api/client";

export interface ApiErrorNavigationState {
  code?: string;
  requestId?: string | null;
  userMessage?: string;
  sourcePath?: string | null;
}

export function buildApiErrorNavigationState(
  error: ApiClientError,
  sourcePath: string,
): ApiErrorNavigationState {
  return {
    code: error.code,
    requestId: error.requestId,
    userMessage: error.userMessage,
    sourcePath: sourcePath === "/conflict" ? null : sourcePath,
  };
}

export function conflictReturnPath(state: ApiErrorNavigationState | null): string | null {
  const path = state?.sourcePath;
  return typeof path === "string" && path.startsWith("/") && path !== "/conflict"
    ? path
    : null;
}
