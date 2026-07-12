import { resolveStatus, type StatusMap, type StatusTone } from "../lib/statusMaps";

const TONE_CLASS: Record<StatusTone, string> = {
  info: "border-cyan-400/30 bg-cyan-400/10 text-cyan-100",
  success: "border-emerald-400/30 bg-emerald-400/10 text-emerald-100",
  warning: "border-amber-400/30 bg-amber-400/10 text-amber-100",
  danger: "border-rose-400/30 bg-rose-400/10 text-rose-100",
  neutral: "border-white/15 bg-white/5 text-slate-200",
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
