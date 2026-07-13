import { useState } from "react";

import { toApiClientError, type ApiClientError } from "../../api/client";
import { getMilestones } from "../../api/evidence";
import { approveResolution, executeResolution, getPaymentTrace, listPaymentResolutions, reconcilePayments, requestRefund, requestUndo, retryReleaseInstruction } from "../../api/payments";
import { LoadingPanel, Notice, RetryPanel } from "../../components/Feedback";
import { useTransactionShell } from "../../components/TransactionShell";
import { useAsyncData } from "../../lib/useAsyncData";
import type { PaymentResolution, ReconcileResult } from "../../types/payments";
import { OperableUnitsPanel } from "./payments/OperableUnitsPanel";
import { paymentErrorMessage } from "./payments/paymentsLogic";
import { ReconcilePanel } from "./payments/ReconcilePanel";
import { ReleaseRetryPanel } from "./payments/ReleaseRetryPanel";
import { TracePanel } from "./payments/TracePanel";

function ReadError({ error, title, onRetry }: { error: ApiClientError; title: string; onRetry: () => void }) {
  if (error.kind === "permission_denied") return <Notice tone="danger">{title} için erişim yetkiniz yok.</Notice>;
  if (error.kind === "network") return <RetryPanel title={`${title} yüklenemedi`} message="Ağ bağlantısı kurulamadı." onRetry={onRetry} />;
  return <RetryPanel title={`${title} yüklenemedi`} message={error.userMessage} onRetry={onRetry} />;
}

export function TransactionPaymentsPage() {
  const { detail, refresh: refreshShell } = useTransactionShell();
  const milestones = useAsyncData(() => getMilestones(detail.id), [detail.id]);
  const resolutions = useAsyncData(() => listPaymentResolutions(detail.id), [detail.id]);
  const trace = useAsyncData(() => getPaymentTrace(detail.id), [detail.id]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<ReconcileResult[] | null>(null);

  async function act<T>(fn: () => Promise<T>, done?: (value: T) => void) {
    setBusy(true);
    setError(null);
    try {
      const value = await fn();
      done?.(value);
      await Promise.all([milestones.refresh(), resolutions.refresh(), trace.refresh(), refreshShell()]);
    } catch (caught) {
      setError(paymentErrorMessage(toApiClientError(caught).code));
    } finally {
      setBusy(false);
    }
  }

  const units = milestones.data?.milestones.flatMap((milestone) => milestone.funding_units) ?? [];
  return (
    <div className="space-y-10">
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <section><h2 className="mb-3 font-semibold text-heading">Mutabakat</h2><ReconcilePanel busy={busy} results={results} onRun={() => void act(() => reconcilePayments(detail.id), (value) => setResults(value.results))} /></section>
      <section className="space-y-3">
        <h2 className="font-semibold text-heading">Fonlama birimleri ve çözümler</h2>
        {milestones.loading && !milestones.data ? <LoadingPanel label="Milestone ve fonlama birimleri yükleniyor…" /> : milestones.error && !milestones.data ? <ReadError error={milestones.error} title="Milestone verileri" onRetry={() => void milestones.refresh()} /> : resolutions.loading && !resolutions.data ? <LoadingPanel label="Ödeme çözümleri yükleniyor…" /> : resolutions.error && !resolutions.data ? <ReadError error={resolutions.error} title="Ödeme çözümleri" onRetry={() => void resolutions.refresh()} /> : <OperableUnitsPanel units={units} resolutions={resolutions.data?.resolutions ?? []} busy={busy} onRequest={(id, operation) => void act(() => operation === "undo" ? requestUndo(id) : requestRefund(id))} onApprove={(id) => void act(() => approveResolution(id))} onExecute={(resolution: PaymentResolution) => void act(() => executeResolution(resolution.id), (value) => { if (value.status === "unknown") setError("Sonuç belirsiz — mutabakat gerekli; tekrar uygulamadan önce yenileyin."); })} />}
      </section>
      <section className="space-y-3"><h2 className="font-semibold text-heading">Release retry</h2>{milestones.data ? <ReleaseRetryPanel units={units} busy={busy} onRetry={(id) => void act(() => retryReleaseInstruction(id), (value) => { if (value.status === "unknown") setError("Sonuç belirsiz — mutabakat gerekli."); })} /> : null}</section>
      <section className="space-y-3"><h2 className="font-semibold text-heading">Ödeme izi</h2>{trace.loading && !trace.data ? <LoadingPanel label="Ödeme izi yükleniyor…" /> : trace.error && !trace.data ? <ReadError error={trace.error} title="Ödeme izi" onRetry={() => void trace.refresh()} /> : <TracePanel trace={trace.data ?? null} />}</section>
    </div>
  );
}
