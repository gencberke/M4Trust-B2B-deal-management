import { useState } from "react";

import { toApiClientError } from "../../api/client";
import { buildRatificationPackage, getCurrentRatificationPackage, submitRatification } from "../../api/ratification";
import { getTrackingPolicy, lockTrackingPolicy, updateTrackingPolicy } from "../../api/tracking";
import { LoadingPanel, Notice, RetryPanel } from "../../components/Feedback";
import { useTransactionShell } from "../../components/TransactionShell";
import { useEntities } from "../../entities/EntityContext";
import { useAsyncData } from "../../lib/useAsyncData";
import type { FundingScheduleSpecInput } from "../../types/ratification";
import type { TrackingMode } from "../../types/tracking";
import { PackagePanel } from "./ratification/PackagePanel";
import { isNoPackageError, RATIFY_NETWORK_WARNING, ratifyErrorMessage, readinessChecklist } from "./ratification/packageLogic";
import { PolicyPanel } from "./ratification/PolicyPanel";
import { policyErrorMessage } from "./ratification/policyLogic";
import { RatifyPanel } from "./ratification/RatifyPanel";

export function TransactionRatificationPage() {
  const { detail, refresh: refreshShell } = useTransactionShell();
  const { selectedEntity } = useEntities();
  const policy = useAsyncData(() => getTrackingPolicy(detail.id), [detail.id]);
  const pkg = useAsyncData(async () => {
    try { return await getCurrentRatificationPackage(detail.id); }
    catch (caught) { const error = toApiClientError(caught); if (isNoPackageError(error)) return null; throw error; }
  }, [detail.id]);
  const [policyBusy, setPolicyBusy] = useState(false);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [packageBusy, setPackageBusy] = useState(false);
  const [packageError, setPackageError] = useState<string | null>(null);
  const [ratifyBusy, setRatifyBusy] = useState(false);
  const [ratifyError, setRatifyError] = useState<string | null>(null);
  const [resultMessage, setResultMessage] = useState<string | null>(null);

  async function savePolicy(confirmed: boolean, mode: TrackingMode) {
    setPolicyBusy(true); setPolicyError(null);
    try { await updateTrackingPolicy(detail.id, { physical_delivery_confirmed: confirmed, tracking_mode: mode }); await policy.refresh(); await pkg.refresh(); }
    catch (caught) { const error = toApiClientError(caught); setPolicyError(error.status === 409 ? policyErrorMessage(error.code, error.detail) : error.userMessage); }
    finally { setPolicyBusy(false); }
  }
  async function lockPolicy() {
    setPolicyBusy(true); setPolicyError(null);
    try { await lockTrackingPolicy(detail.id); await policy.refresh(); await pkg.refresh(); }
    catch (caught) { const error = toApiClientError(caught); setPolicyError(error.status === 409 ? policyErrorMessage(error.code, error.detail) : error.userMessage); }
    finally { setPolicyBusy(false); }
  }
  async function build(spec: FundingScheduleSpecInput) {
    setPackageBusy(true); setPackageError(null);
    try { await buildRatificationPackage(detail.id, { funding_schedule_spec: spec }); await pkg.refresh(); await refreshShell(); }
    catch (caught) { const error = toApiClientError(caught); setPackageError(error.status === 409 ? readinessChecklist(error.code) : error.userMessage); }
    finally { setPackageBusy(false); }
  }
  async function ratify() {
    if (!pkg.data) return;
    setRatifyBusy(true); setRatifyError(null); setResultMessage(null);
    try {
      const outcome = await submitRatification(pkg.data.id);
      setResultMessage(outcome.funding_triggered ? "Fonlama başlatıldı." : outcome.package_status === "complete" ? "Paket zaten tamamlanmış; onay kaydı korunuyor." : "Onayınız kaydedildi.");
      await pkg.refresh(); await refreshShell();
    } catch (caught) {
      const error = toApiClientError(caught);
      setRatifyError(error.kind === "network" ? RATIFY_NETWORK_WARNING : ratifyErrorMessage(error.code));
    } finally { setRatifyBusy(false); }
  }

  return <div className="space-y-10">
    <section className="space-y-3"><h2 className="text-base font-semibold text-heading">Takip politikası</h2>
      {policy.loading && !policy.data ? <LoadingPanel label="Takip politikası yükleniyor…" /> : policy.error && !policy.data ? policy.error.kind === "permission_denied" ? <Notice tone="danger">Takip politikasını görme veya yönetme yetkiniz yok.</Notice> : <RetryPanel title="Takip politikası yüklenemedi" message={policy.error.userMessage} retrying={policy.loading} onRetry={() => void policy.refresh()} /> : policy.data ? <PolicyPanel key={`${policy.data.tracking_policy.configured_at}-${policy.data.tracking_policy.locked_at}`} view={policy.data} busy={policyBusy} error={policyError} onSave={(confirmed, mode) => void savePolicy(confirmed, mode)} onLock={() => void lockPolicy()} /> : <Notice tone="info">Takip politikası henüz oluşturulmadı.</Notice>}
    </section>
    <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="text-base font-semibold text-heading">Onay paketi</h2><button type="button" className="text-sm text-primary disabled:opacity-50" disabled={pkg.loading} onClick={() => void pkg.refresh()}>Yenile</button></div>
      {pkg.loading && !pkg.data ? <LoadingPanel label="Onay paketi yükleniyor…" /> : pkg.error ? pkg.error.kind === "permission_denied" ? <Notice tone="danger">Onay paketine erişim yetkiniz yok.</Notice> : <RetryPanel title="Onay paketi yüklenemedi" message={pkg.error.userMessage} retrying={pkg.loading} onRetry={() => void pkg.refresh()} /> : <PackagePanel pkg={pkg.data ?? null} extraction={detail.extraction} busy={packageBusy} error={packageError} onBuild={(spec) => void build(spec)} />}
    </section>
    <section className="space-y-3"><h2 className="text-base font-semibold text-heading">Taraf onayı</h2><RatifyPanel pkg={pkg.data ?? null} actingEntityName={selectedEntity?.legal_name ?? ""} busy={ratifyBusy} error={ratifyError} resultMessage={resultMessage} onRatify={() => void ratify()} /></section>
  </div>;
}
