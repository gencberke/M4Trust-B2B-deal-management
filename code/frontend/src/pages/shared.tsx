import type { ReactNode } from "react";

import { ApiClientError } from "../api/client";
import { Notice } from "../components/Feedback";

export const inputClass =
  "w-full rounded-2xl border border-border bg-card px-4 py-3 text-sm text-heading shadow-sm outline-none transition placeholder:text-muted focus:border-primary focus:ring-3 focus:ring-primary-soft";
export const buttonClass =
  "button-primary";
export const secondaryButtonClass =
  "button-secondary";

export function FormError({ error }: { error: ApiClientError | null }) {
  return error ? <Notice tone="danger">{error.userMessage}</Notice> : null;
}

export function parseAddress(value: string): Record<string, unknown> | null {
  if (!value.trim()) return null;
  const parsed = JSON.parse(value) as unknown;
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("Adres JSON nesne olmalıdır.");
  }
  return parsed as Record<string, unknown>;
}

export function Info({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <dt className="text-xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-2 break-words text-sm text-heading">{value}</dd>
    </div>
  );
}
