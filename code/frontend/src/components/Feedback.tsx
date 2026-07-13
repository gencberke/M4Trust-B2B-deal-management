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
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-primary">
          {eyebrow}
        </p>
      ) : null}
      <h1 className="text-3xl font-bold tracking-tight text-heading sm:text-4xl">{title}</h1>
      {description ? (
        <p className="mt-3 max-w-2xl text-sm leading-6 text-body">{description}</p>
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
    info: "border-primary/20 bg-info-soft text-primary",
    success: "border-positive/20 bg-positive-soft text-positive",
    warning: "border-amber-300 bg-warning-soft text-amber-800",
    danger: "border-rose-300 bg-danger-soft text-rose-700",
  };
  return <div className={`rounded-2xl border px-4 py-3 text-sm leading-6 ${tones[tone]}`}>{children}</div>;
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
    <div className="card-surface p-8 text-center">
      <p className="text-base font-semibold text-heading">{title}</p>
      {description ? <p className="mt-2 text-sm text-muted">{description}</p> : null}
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
        <div key={item.label} className="rounded-2xl border border-border bg-card p-4 shadow-sm">
          <dt className="text-xs uppercase tracking-wide text-muted">{item.label}</dt>
          <dd className="mt-2 break-words text-sm text-heading">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function LoadingPanel({ label = "Yükleniyor…" }: { label?: string }) {
  return (
    <div className="card-surface flex min-h-48 items-center justify-center text-sm text-muted">
      {label}
    </div>
  );
}

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <span aria-hidden="true" className={`block animate-pulse rounded-xl bg-slate-200 ${className}`} />;
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return <div className="card-surface space-y-3 p-5" role="status" aria-label="İçerik yükleniyor">{Array.from({ length: rows }, (_, index) => <div key={index} className="grid grid-cols-[5rem_1fr_7rem] gap-4"><Skeleton /><Skeleton /><Skeleton /></div>)}</div>;
}

export function SkeletonCards({ cards = 3 }: { cards?: number }) {
  return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" role="status" aria-label="Kartlar yükleniyor">{Array.from({ length: cards }, (_, index) => <div key={index} className="card-surface space-y-4 p-5"><Skeleton className="h-3 w-24" /><Skeleton className="h-8 w-2/3" /><Skeleton /></div>)}</div>;
}

export function TransactionShellSkeleton() {
  return <div className="space-y-6" role="status" aria-label="İşlem yükleniyor"><Skeleton className="h-4 w-28" /><Skeleton className="h-10 w-64" /><Skeleton className="h-20 w-full" /><SkeletonRows rows={3} /></div>;
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
    <div className="rounded-3xl border border-rose-300 bg-danger-soft p-6">
      <h2 className="text-lg font-semibold text-heading">{title}</h2>
      <p className="mt-2 text-sm text-rose-700">{message}</p>
      <button
        className="mt-4 rounded-2xl bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        disabled={retrying}
        onClick={onRetry}
      >
        {retrying ? "Tekrar deneniyor…" : "Tekrar dene"}
      </button>
    </div>
  );
}
