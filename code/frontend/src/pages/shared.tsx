import type { ReactNode } from "react";

import { ApiClientError } from "../api/client";
import { Notice } from "../components/Feedback";

export const inputClass =
  "w-full rounded-2xl border border-white/10 bg-slate-900/80 px-4 py-3 text-sm text-white outline-none transition placeholder:text-slate-500 focus:border-cyan-300";
export const buttonClass =
  "inline-flex items-center justify-center rounded-2xl bg-cyan-300 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50";
export const secondaryButtonClass =
  "inline-flex items-center justify-center rounded-2xl border border-white/15 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/10";

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
    <div className="rounded-2xl border border-white/10 bg-slate-950/50 p-4">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-2 break-words text-sm text-white">{value}</dd>
    </div>
  );
}
