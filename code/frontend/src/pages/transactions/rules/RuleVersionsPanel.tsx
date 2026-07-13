import { useMemo, useState } from "react";

import { EmptyState, Notice } from "../../../components/Feedback";
import { ResponsiveTable } from "../../../components/ResponsiveTable";
import { StatusBadge } from "../../../components/StatusBadge";
import { formatDateTime, shortId } from "../../../lib/format";
import { ruleSetStatusMap, validatorStatusMap } from "../../../lib/statusMaps";
import type { ExtractionRevisionInput, RuleSetVersionHistory, RuleSetVersionPublicView } from "../../../types/rules";
import { buttonClass, inputClass, secondaryButtonClass } from "../../shared";
import { diffExtraction } from "./ruleDiff";
import {
  buildRevisionPayload,
  formStateFromExtraction,
  type RevisionFormState,
} from "./revisionForm";

export function RuleVersionsPanel({
  history,
  editable,
  onRevise,
  onRevalidate,
  busy,
  actionError,
}: {
  history: RuleSetVersionHistory;
  editable: boolean;
  onRevise: (payload: ExtractionRevisionInput) => void;
  onRevalidate: () => void;
  busy: boolean;
  actionError: string | null;
}) {
  const { versions, current_version: current, current_version_id: currentId } = history;
  const [selectedA, setSelectedA] = useState<string>(versions[1]?.id ?? "");
  const [selectedB, setSelectedB] = useState<string>(current?.id ?? versions[0]?.id ?? "");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<RevisionFormState | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const byId = useMemo(() => new Map(versions.map((v) => [v.id, v])), [versions]);
  const diffRows = useMemo(
    () => diffExtraction(byId.get(selectedA)?.extraction ?? null, byId.get(selectedB)?.extraction ?? null),
    [byId, selectedA, selectedB],
  );

  if (versions.length === 0) {
    return <EmptyState title="Kural sürümü yok" description="Bu işlem için henüz kural sürümü üretilmedi." />;
  }

  function startEdit() {
    if (!current) return;
    setForm(formStateFromExtraction(current.extraction));
    setFormError(null);
    setEditing(true);
  }

  function submitRevision() {
    if (!form) return;
    const result = buildRevisionPayload(form);
    if (!result.ok || !result.payload) {
      setFormError(result.error ?? "Form geçersiz.");
      return;
    }
    setFormError(null);
    onRevise(result.payload);
  }

  return (
    <div className="space-y-5">
      <ResponsiveTable
        caption="Kural sürümleri"
        head={["Sürüm", "Durum", "Doğrulama", "Hash", "Oluşturma"]}
        emptyLabel="Sürüm yok"
        rows={versions.map((v: RuleSetVersionPublicView) => ({
          key: v.id,
          cells: [
            `v${v.version}${v.id === currentId ? " (güncel)" : ""}`,
            <StatusBadge key="s" value={v.status} map={ruleSetStatusMap} />,
            <StatusBadge key="vs" value={v.validator_status} map={validatorStatusMap} />,
            <span key="h" className="font-mono text-xs">{shortId(v.rules_hash, 12)}</span>,
            formatDateTime(v.created_at),
          ],
        }))}
      />

      {versions.length >= 2 ? (
        <div className="space-y-3 rounded-2xl border border-white/10 bg-slate-950/40 p-4">
          <h4 className="text-sm font-medium text-slate-300">Sürüm karşılaştırma</h4>
          <div className="flex flex-wrap gap-3">
            <label className="text-xs text-slate-400">
              Önceki
              <select className={`mt-1 block ${inputClass}`} value={selectedA} onChange={(e) => setSelectedA(e.target.value)}>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>v{v.version}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-slate-400">
              Sonraki
              <select className={`mt-1 block ${inputClass}`} value={selectedB} onChange={(e) => setSelectedB(e.target.value)}>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>v{v.version}</option>
                ))}
              </select>
            </label>
          </div>
          {diffRows.length === 0 ? (
            <p className="text-sm text-slate-400">Seçili sürümler arasında fark yok.</p>
          ) : (
            <ResponsiveTable
              caption="Sürüm farkı"
              head={["Alan", "Değişim", "Önceki", "Sonraki"]}
              emptyLabel="Fark yok"
              rows={diffRows.map((r, i) => ({
                key: `${r.path}-${i}`,
                cells: [
                  <span key="p" className="font-mono text-xs">{r.path}</span>,
                  r.kind,
                  r.before,
                  r.after,
                ],
              }))}
            />
          )}
        </div>
      ) : null}

      {actionError ? <Notice tone="danger">{actionError}</Notice> : null}

      {!editable ? (
        <Notice tone="info">Onay sonrası kurallar değiştirilemez.</Notice>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-3">
            <button type="button" className={secondaryButtonClass} disabled={busy} onClick={() => onRevalidate()}>
              Güncel sürümü yeniden doğrula
            </button>
            {!editing ? (
              <button type="button" className={buttonClass} disabled={busy || !current} onClick={startEdit}>
                Kuralları düzenle
              </button>
            ) : null}
          </div>

          {editing && form ? (
            <RevisionForm
              form={form}
              setForm={(updater) =>
                setForm((previous) => (previous ? updater(previous) : previous))
              }
              formError={formError}
              busy={busy}
              onSubmit={submitRevision}
              onCancel={() => setEditing(false)}
            />
          ) : null}
        </div>
      )}
    </div>
  );
}

function RevisionForm({
  form,
  setForm,
  formError,
  busy,
  onSubmit,
  onCancel,
}: {
  form: RevisionFormState;
  setForm: (updater: (prev: RevisionFormState) => RevisionFormState) => void;
  formError: string | null;
  busy: boolean;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="space-y-4 rounded-2xl border border-white/10 bg-slate-950/40 p-4">
      <Notice tone="warning">
        Sözleşme alıntıları (source_quote) redakte okumada gösterilmez ve bu formda yer almaz;
        değiştirmediğiniz kuralların alıntıları sunucu tarafında korunur. Bu ekran yeni bir kural
        eklemek için uygun değildir.
      </Notice>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm text-slate-300">
          Sözleşme No
          <input className={`mt-1 ${inputClass}`} value={form.contract_id} onChange={(e) => setForm((p) => ({ ...p, contract_id: e.target.value }))} />
        </label>
        <label className="text-sm text-slate-300">
          Para birimi
          <select className={`mt-1 block ${inputClass}`} value={form.currency} onChange={(e) => setForm((p) => ({ ...p, currency: e.target.value }))}>
            {["TRY", "USD", "EUR", "OTHER"].map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="text-sm text-slate-300">
          Alıcı adı
          <input className={`mt-1 ${inputClass}`} value={form.buyer_name} onChange={(e) => setForm((p) => ({ ...p, buyer_name: e.target.value }))} />
        </label>
        <label className="text-sm text-slate-300">
          Satıcı adı
          <input className={`mt-1 ${inputClass}`} value={form.seller_name} onChange={(e) => setForm((p) => ({ ...p, seller_name: e.target.value }))} />
        </label>
        <label className="text-sm text-slate-300">
          Toplam tutar
          <input className={`mt-1 ${inputClass}`} value={form.total_amount} onChange={(e) => setForm((p) => ({ ...p, total_amount: e.target.value }))} />
        </label>
        <label className="text-sm text-slate-300">
          Teslim tarihi (YYYY-AA-GG)
          <input className={`mt-1 ${inputClass}`} value={form.delivery_deadline} onChange={(e) => setForm((p) => ({ ...p, delivery_deadline: e.target.value }))} />
        </label>
      </div>

      <div className="space-y-2">
        <h5 className="text-xs uppercase tracking-wide text-slate-500">Ödeme kuralları</h5>
        {form.payment_rules.map((rule, i) => (
          <div key={i} className="grid gap-2 rounded-xl border border-white/10 p-3 sm:grid-cols-2">
            <label className="text-xs text-slate-400">
              Aşama
              <input className={`mt-1 ${inputClass}`} value={rule.milestone} onChange={(e) => setForm((p) => updateRule(p, i, { milestone: e.target.value }))} />
            </label>
            <label className="text-xs text-slate-400">
              Tetikleyici
              <select className={`mt-1 block ${inputClass}`} value={rule.trigger} onChange={(e) => setForm((p) => updateRule(p, i, { trigger: e.target.value }))}>
                {["approval", "e_invoice", "delivery_video", "manual_review"].map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="text-xs text-slate-400">
              Yüzde
              <input className={`mt-1 ${inputClass}`} value={rule.percentage} onChange={(e) => setForm((p) => updateRule(p, i, { percentage: e.target.value }))} />
            </label>
            <label className="text-xs text-slate-400">
              Güven (0-1)
              <input className={`mt-1 ${inputClass}`} value={rule.confidence} onChange={(e) => setForm((p) => updateRule(p, i, { confidence: e.target.value }))} />
            </label>
            <label className="text-xs text-slate-400 sm:col-span-2">
              Gerekli kanıt (virgülle: contract, e_irsaliye, video)
              <input className={`mt-1 ${inputClass}`} value={rule.required_evidence} onChange={(e) => setForm((p) => updateRule(p, i, { required_evidence: e.target.value }))} />
            </label>
          </div>
        ))}
      </div>

      <label className="block text-sm text-slate-300">
        Risk işaretleri (virgülle)
        <input className={`mt-1 ${inputClass}`} value={form.risk_flags} onChange={(e) => setForm((p) => ({ ...p, risk_flags: e.target.value }))} />
      </label>
      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input type="checkbox" checked={form.needs_manual_review} onChange={(e) => setForm((p) => ({ ...p, needs_manual_review: e.target.checked }))} />
        Manuel inceleme gereksin
      </label>

      {formError ? <Notice tone="danger">{formError}</Notice> : null}

      <div className="flex gap-3">
        <button type="button" className={buttonClass} disabled={busy} onClick={onSubmit}>
          {busy ? "Gönderiliyor…" : "Revizyonu gönder"}
        </button>
        <button type="button" className={secondaryButtonClass} disabled={busy} onClick={onCancel}>
          Vazgeç
        </button>
      </div>
    </div>
  );
}

function updateRule(
  state: RevisionFormState,
  index: number,
  patch: Partial<RevisionFormState["payment_rules"][number]>,
): RevisionFormState {
  const payment_rules = state.payment_rules.map((r, i) => (i === index ? { ...r, ...patch } : r));
  return { ...state, payment_rules };
}
