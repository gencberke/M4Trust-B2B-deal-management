import { useState } from "react";

import { toApiClientError } from "../../api/client";
import { buildRatificationPackage, getCurrentRatificationPackage, submitRatification } from "../../api/ratification";
import { getTrackingPolicy, lockTrackingPolicy, updateTrackingPolicy } from "../../api/tracking";
import { useTransactionShell } from "../../components/TransactionShell";
import { useEntities } from "../../entities/EntityContext";
import { useAsyncData } from "../../lib/useAsyncData";
import type { FundingScheduleSpecInput } from "../../types/ratification";
import type { TrackingMode } from "../../types/tracking";
import { isNoPackageError, RATIFY_NETWORK_WARNING, ratifyErrorMessage, readinessChecklist } from "./ratification/packageLogic";
import { policyErrorMessage } from "./ratification/policyLogic";
import { PolicyLockStep } from "./ratification/PolicyLockStep";
import { PackageReadinessStep } from "./ratification/PackageReadinessStep";
import { RatifyStep } from "./ratification/RatifyStep";

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

  return <div className="space-y-6">
    <PolicyLockStep view={policy.data ?? null} loading={policy.loading} loadError={policy.error} busy={policyBusy} error={policyError} onRefresh={() => void policy.refresh()} onSave={(confirmed, mode) => void savePolicy(confirmed, mode)} onLock={() => void lockPolicy()} />
    <PackageReadinessStep detail={detail} policy={policy.data ?? null} pkg={pkg.data ?? null} loading={pkg.loading} loadError={pkg.error} busy={packageBusy} error={packageError} onRefresh={() => void pkg.refresh()} onBuild={(spec) => void build(spec)} />
    <RatifyStep pkg={pkg.data ?? null} actingEntityName={selectedEntity?.legal_name ?? ""} busy={ratifyBusy} error={ratifyError} resultMessage={resultMessage} onRatify={() => void ratify()} />
  </div>;
}
