import type { ReactNode } from "react";

export function PageHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
}) {
  return (
    <header className="mb-8">
      {eyebrow ? (
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">
          {eyebrow}
        </p>
      ) : null}
      <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">{title}</h1>
      {description ? (
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">{description}</p>
      ) : null}
    </header>
  );
}

export function Notice({
  children,
  tone = "info",
}: {
  children: ReactNode;
  tone?: "info" | "success" | "warning" | "danger";
}) {
  const tones = {
    info: "border-cyan-400/20 bg-cyan-400/10 text-cyan-100",
    success: "border-emerald-400/20 bg-emerald-400/10 text-emerald-100",
    warning: "border-amber-400/20 bg-amber-400/10 text-amber-100",
    danger: "border-rose-400/20 bg-rose-400/10 text-rose-100",
  };
  return <div className={`rounded-2xl border px-4 py-3 text-sm ${tones[tone]}`}>{children}</div>;
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-3xl border border-white/10 bg-white/5 p-8 text-center">
      <p className="text-base font-semibold text-white">{title}</p>
      {description ? <p className="mt-2 text-sm text-slate-400">{description}</p> : null}
      {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
    </div>
  );
}

export function KeyValueGrid({
  items,
}: {
  items: { label: string; value: ReactNode }[];
}) {
  return (
    <dl className="grid gap-3 sm:grid-cols-2">
      {items.map((item) => (
        <div key={item.label} className="rounded-2xl border border-white/10 bg-slate-950/50 p-4">
          <dt className="text-xs uppercase tracking-wide text-slate-500">{item.label}</dt>
          <dd className="mt-2 break-words text-sm text-white">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function LoadingPanel({ label = "Yükleniyor…" }: { label?: string }) {
  return (
    <div className="flex min-h-48 items-center justify-center rounded-3xl border border-white/10 bg-white/5 text-sm text-slate-300">
      {label}
    </div>
  );
}

export function RetryPanel({
  title,
  message,
  onRetry,
  retrying = false,
}: {
  title: string;
  message: string;
  onRetry: () => void;
  retrying?: boolean;
}) {
  return (
    <div className="rounded-3xl border border-rose-400/20 bg-rose-400/10 p-6">
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <p className="mt-2 text-sm text-rose-100">{message}</p>
      <button
        className="mt-4 rounded-2xl bg-white px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50"
        disabled={retrying}
        onClick={onRetry}
      >
        {retrying ? "Tekrar deneniyor…" : "Tekrar dene"}
      </button>
    </div>
  );
}
