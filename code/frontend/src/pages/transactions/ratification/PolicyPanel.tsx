import { useState } from "react";

import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { KeyValueGrid, Notice } from "../../../components/Feedback";
import { StatusBadge } from "../../../components/StatusBadge";
import { formatDateTime } from "../../../lib/format";
import { policyStatusMap } from "../../../lib/statusMaps";
import type { TrackingMode, TrackingPolicyView } from "../../../types/tracking";
import { buttonClass, secondaryButtonClass } from "../../shared";
import { recommendationLabel, reasonCodeLabel, TRACKING_MODE_LABEL } from "./policyLogic";

export function PolicyPanel({ view, busy, error, onSave, onLock }: {
  view: TrackingPolicyView;
  busy: boolean;
  error: string | null;
  onSave: (confirmed: boolean, mode: TrackingMode) => void;
  onLock: () => void;
}) {
  const policy = view.tracking_policy;
  const [confirmed, setConfirmed] = useState(policy.manager_physical_delivery_confirmed ?? false);
  const [mode, setMode] = useState<TrackingMode>((policy.tracking_mode as TrackingMode) || "off");
  const [lockOpen, setLockOpen] = useState(false);

  const locked = policy.status === "locked";
  return (
    <div className="space-y-4">
      <KeyValueGrid items={[
        { label: "Durum", value: <StatusBadge value={policy.status} map={policyStatusMap} /> },
        { label: "Sistem önerisi", value: recommendationLabel(policy.recommendation) },
        { label: "Takip modu", value: TRACKING_MODE_LABEL[policy.tracking_mode] ?? policy.tracking_mode },
        { label: "Kilit zamanı", value: formatDateTime(policy.locked_at) },
      ]} />
      {policy.recommendation_reason_codes.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-body">
          {policy.recommendation_reason_codes.map((code) => <li key={code}>{reasonCodeLabel(code)}</li>)}
        </ul>
      ) : <p className="text-sm text-muted">Öneri gerekçesi bulunmuyor.</p>}
      <p className="text-sm text-body">
        Sözleşmesel kanıtlar: {view.contractual_required_evidence.length > 0 ? view.contractual_required_evidence.join(", ") : "Yok"}
      </p>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      {locked ? (
        <Notice tone="success">Politika kilitli ve salt okunur. Sözleşmesel kanıt şartları zayıflatılamaz.</Notice>
      ) : !view.ready_for_policy ? (
        <Notice tone="warning">Politika bu işlem aşamasında yapılandırılamıyor.</Notice>
      ) : (
        <fieldset className="space-y-4" disabled={busy}>
          <legend className="text-sm font-medium text-heading">Yönetici seçimi</legend>
          <label className="flex items-center gap-2 text-sm text-body">
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            Fiziksel teslimatı doğruluyorum
          </label>
          <div className="grid gap-2 sm:grid-cols-3">
            {(["off", "document_only", "document_and_video"] as TrackingMode[]).map((value) => (
              <label key={value} className="rounded-2xl border border-border p-3 text-sm text-body">
                <input className="mr-2" type="radio" name="tracking-mode" value={value} checked={mode === value} onChange={() => setMode(value)} />
                {TRACKING_MODE_LABEL[value]}
              </label>
            ))}
          </div>
          <div className="flex flex-wrap gap-3">
            <button className={secondaryButtonClass} type="button" onClick={() => onSave(confirmed, mode)} disabled={busy}>Kaydet</button>
            <button className={buttonClass} type="button" onClick={() => setLockOpen(true)} disabled={busy}>Politikayı kilitle</button>
          </div>
        </fieldset>
      )}
      <ConfirmDialog open={lockOpen} title="Takip politikasını kilitle" description="Kilitlendikten sonra politika değiştirilemez. Seçimi ve sözleşmesel kanıt şartlarını kontrol edin." confirmLabel="Kilitle" tone="danger" busy={busy} onCancel={() => setLockOpen(false)} onConfirm={() => { setLockOpen(false); onLock(); }} />
    </div>
  );
}
