import { StatusBadge } from "../../../components/StatusBadge";
import { validatorStatusMap } from "../../../lib/statusMaps";
import type { ValidatorReport } from "../../../types/transactions";

export function ValidatorFindingsPanel({ validator }: { validator: ValidatorReport | null }) {
  if (!validator) {
    return <p className="text-sm text-slate-400">Doğrulama raporu henüz yok.</p>;
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <h3 className="text-sm font-medium text-slate-300">Doğrulama durumu</h3>
        <StatusBadge value={validator.status} map={validatorStatusMap} />
      </div>
      {validator.findings && validator.findings.length > 0 ? (
        <ul className="space-y-2">
          {validator.findings.map((finding, i) => (
            <li
              key={`${finding.code}-${i}`}
              className="rounded-2xl border border-white/10 bg-slate-950/50 p-3 text-sm"
            >
              <span className="font-mono text-xs text-slate-400">{finding.code}</span>
              <span className="ml-2 text-slate-300">({finding.severity})</span>
              {finding.message ? <p className="mt-1 text-slate-200">{finding.message}</p> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-400">Bulgu yok.</p>
      )}
    </div>
  );
}
