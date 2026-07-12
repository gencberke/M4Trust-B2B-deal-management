import type { ReactNode } from "react";

import type { StatusTone } from "../lib/statusMaps";
import { formatDateTime } from "../lib/format";

export interface TimelineItem {
  id: string | number;
  title: string;
  tone?: StatusTone;
  timestamp: string;
  children?: ReactNode;
}

const DOT_CLASS: Record<StatusTone, string> = {
  info: "bg-cyan-300",
  success: "bg-emerald-300",
  warning: "bg-amber-300",
  danger: "bg-rose-300",
  neutral: "bg-slate-400",
};

/** Sıralı olay listesi (`<ol>`); ton renk + metinle taşınır (renk tek başına değil). */
export function Timeline({
  items,
  emptyLabel,
}: {
  items: TimelineItem[];
  emptyLabel: string;
}) {
  if (items.length === 0) {
    return <p className="text-sm text-slate-400">{emptyLabel}</p>;
  }
  return (
    <ol className="space-y-4">
      {items.map((item) => (
        <li key={item.id} className="flex gap-3">
          <span
            aria-hidden="true"
            className={`mt-1.5 size-2.5 shrink-0 rounded-full ${DOT_CLASS[item.tone ?? "neutral"]}`}
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm font-medium text-white">{item.title}</p>
              <time className="text-xs text-slate-500">{formatDateTime(item.timestamp)}</time>
            </div>
            {item.children ? (
              <div className="mt-1 text-xs text-slate-400">{item.children}</div>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
