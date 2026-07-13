import { resolveStatus, type StatusMap, type StatusTone } from "../lib/statusMaps";

const TONE_CLASS: Record<StatusTone, string> = {
  info: "border-primary/30 bg-info-soft text-primary",
  success: "border-emerald-400/30 bg-positive-soft text-positive",
  warning: "border-amber-400/30 bg-warning-soft text-amber-800",
  danger: "border-rose-400/30 bg-danger-soft text-rose-700",
  neutral: "border-border bg-card shadow-card text-body",
};

/**
 * Herhangi bir enum statüsü için renk + metin rozet. Renk her zaman
 * etiket metniyle birlikte gelir (renk-bağımsız erişilebilirlik, master §10).
 */
export function StatusBadge({ value, map }: { value: string | null; map: StatusMap }) {
  const { label, tone } = resolveStatus(map, value);
  return (
    <span
      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${TONE_CLASS[tone]}`}
    >
      {label}
    </span>
  );
}
