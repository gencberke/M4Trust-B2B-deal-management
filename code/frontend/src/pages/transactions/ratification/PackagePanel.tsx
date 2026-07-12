import { useMemo, useState } from "react";

import { EmptyState, KeyValueGrid, Notice } from "../../../components/Feedback";
import { ResponsiveTable } from "../../../components/ResponsiveTable";
import { StatusBadge } from "../../../components/StatusBadge";
import { formatAmountMinor, formatPercentBps } from "../../../lib/format";
import { packageStatusMap } from "../../../lib/statusMaps";
import type { FundingScheduleSpecInput, RatificationPackagePublicView } from "../../../types/ratification";
import type { RedactedExtraction } from "../../../types/transactions";
import { buttonClass, inputClass, secondaryButtonClass } from "../../shared";
import { buildSpecFromForm, scheduleRows, type BuildSpecFormRow } from "./packageLogic";

export function PackagePanel({ pkg, extraction, busy, error, onBuild }: {
  pkg: RatificationPackagePublicView | null;
  extraction: RedactedExtraction | null;
  busy: boolean;
  error: string | null;
  onBuild: (spec: FundingScheduleSpecInput) => void;
}) {
  const initialRows = useMemo<BuildSpecFormRow[]>(() => (extraction?.payment_rules ?? []).map((_, rule_index) => ({ rule_index, release_mode: "all_or_nothing", tranche_count: "" })), [extraction]);
  const [rows, setRows] = useState(initialRows);
  const [formError, setFormError] = useState<string | null>(null);

  function build() {
    const result = buildSpecFromForm(rows);
    if (!result.ok) return setFormError(result.error);
    setFormError(null);
    onBuild(result.spec);
  }

  if (!pkg) return (
    <div className="space-y-4">
      <EmptyState title="Henüz onay paketi yok" description="Hazırlık şartları tamamlandığında güncel kurallardan değişmez bir paket oluşturun." />
      {rows.map((row, index) => (
        <div key={row.rule_index} className="grid gap-3 rounded-2xl border border-white/10 p-4 sm:grid-cols-3">
          <span className="text-sm text-slate-300">{extraction?.payment_rules[index]?.milestone ?? `Kural ${index + 1}`}</span>
          <select className={inputClass} value={row.release_mode} onChange={(e) => setRows((old) => old.map((item, i) => i === index ? { ...item, release_mode: e.target.value as BuildSpecFormRow["release_mode"] } : item))}>
            <option value="all_or_nothing">Tek seferde</option><option value="fixed_tranches">Sabit dilimler</option>
          </select>
          <input className={inputClass} type="number" min={2} aria-label={`Kural ${index + 1} dilim sayısı`} placeholder="Dilim sayısı" disabled={row.release_mode !== "fixed_tranches"} value={row.tranche_count} onChange={(e) => setRows((old) => old.map((item, i) => i === index ? { ...item, tranche_count: e.target.value } : item))} />
        </div>
      ))}
      {formError ? <Notice tone="danger">{formError}</Notice> : null}{error ? <Notice tone="danger">{error}</Notice> : null}
      <button type="button" className={buttonClass} disabled={busy || !extraction} onClick={build}>{busy ? "Oluşturuluyor…" : "Paketi oluştur"}</button>
    </div>
  );

  const schedule = scheduleRows(pkg.canonical_payload);
  const summary = pkg.canonical_payload.commercial_summary;
  return <div className="space-y-5">
    {pkg.status === "superseded" ? <Notice tone="warning">Bu paket yenilenmiş. Güncel paketi yükleyin.</Notice> : null}
    <KeyValueGrid items={[
      { label: "Paket durumu", value: <StatusBadge value={pkg.status} map={packageStatusMap} /> },
      { label: "Paket sürümü", value: `v${pkg.version}` },
      { label: "Toplam", value: summary ? formatAmountMinor(summary.total_amount_minor, summary.currency) : "—" },
      { label: "Teslim tarihi", value: summary?.delivery_deadline ?? "—" },
    ]} />
    <div className="rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-4">
      <p className="text-xs uppercase tracking-wide text-cyan-200">Paket hash'i</p><p className="mt-2 break-all font-mono text-sm text-white">{pkg.package_hash}</p>
      <p className="mt-2 text-xs text-slate-400">İki taraf da aynı hash'i görmelidir.</p>
      <button className={`${secondaryButtonClass} mt-3`} type="button" onClick={() => void navigator.clipboard?.writeText(pkg.package_hash)}>Hash'i kopyala</button>
    </div>
    <ResponsiveTable caption="Fonlama takvimi" head={["Aşama", "Tetikleyici", "Oran", "Tutar", "Serbest bırakma", "Kanıt / birimler"]} emptyLabel="Takvim satırı yok" rows={schedule.map((row) => ({ key: String(row.rule_index), cells: [row.title, row.trigger_type, formatPercentBps(row.basis_points), formatAmountMinor(row.amount_minor, row.currency), row.release_mode, <div key="units"><div>{row.required_evidence.join(", ") || "—"}</div>{row.units.map((unit) => <div key={unit.sequence} className="mt-1 text-xs text-slate-400">#{unit.sequence} · {formatAmountMinor(unit.amount_minor, row.currency)} · {unit.eligibility_type}</div>)}</div>] }))} />
    {error ? <Notice tone="danger">{error}</Notice> : null}
  </div>;
}
