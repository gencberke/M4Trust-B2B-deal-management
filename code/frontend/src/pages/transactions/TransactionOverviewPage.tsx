import { useState } from "react";

import { retryExtraction } from "../../api/transactions";
import { ApiClientError, toApiClientError } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { NextActionCard } from "../../components/LifecycleStepper";
import { KeyValueGrid, Notice } from "../../components/Feedback";
import { ResponsiveTable } from "../../components/ResponsiveTable";
import { StatusBadge } from "../../components/StatusBadge";
import { Timeline } from "../../components/Timeline";
import { useTransactionShell } from "../../components/TransactionShell";
import { formatAmountMajor, formatRatioPercent } from "../../lib/format";
import { validatorStatusMap } from "../../lib/statusMaps";
import { usePolling } from "../../lib/usePolling";
import type { ExtractionRetryResponse } from "../../types/transactions";
import { FormError } from "../shared";
import { safeEventItems, shouldPoll } from "./overviewProjection";

export function TransactionOverviewPage() {
  const { detail, refresh, lifecycle, lifecycleRole } = useTransactionShell();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<ApiClientError | null>(null);
  const [retryResult, setRetryResult] = useState<ExtractionRetryResponse | null>(null);

  // Yalnız yükleme/çıkarım sürerken arka planda yenile (odak çalmaz).
  usePolling(() => void refresh(), {
    active: shouldPoll(detail.state),
    intervalMs: 4000,
  });

  const extraction = detail.extraction;
  const validator = detail.validator;
  const events = safeEventItems(detail.events);

  async function onConfirmRetry() {
    setRetrying(true);
    setRetryError(null);
    setRetryResult(null);
    try {
      const result = await retryExtraction(detail.id);
      setRetryResult(result);
      setDialogOpen(false);
      await refresh();
    } catch (caught) {
      const error = toApiClientError(caught);
      setRetryError(error);
      setDialogOpen(false);
    } finally {
      setRetrying(false);
    }
  }

  const showRetry = detail.state === "extracting";

  return (
    <div className="space-y-8">
      <NextActionCard transactionId={detail.id} lifecycle={lifecycle} role={lifecycleRole} />

      <section className="space-y-4">
        <h2 className="text-base font-semibold text-heading">İşlem özeti</h2>
        <KeyValueGrid items={[
          { label: "Durum", value: lifecycle.label },
          { label: "Aktif adım", value: lifecycle.stepLabel },
          { label: "Sözleşme No", value: extraction?.contract_id ?? "—" },
          { label: "Alıcı", value: extraction?.parties.buyer.name ?? "—" },
          { label: "Satıcı", value: extraction?.parties.seller.name ?? "—" },
          { label: "Toplam tutar", value: extraction ? formatAmountMajor(extraction.commercial_terms.total_amount, extraction.commercial_terms.currency) : "—" },
        ]} />
      </section>

      <section className="space-y-3">
        <h2 className="text-base font-semibold text-heading">Olay zaman çizelgesi</h2>
        <Timeline emptyLabel="Henüz olay yok." items={events.map((item) => ({ id: item.id, title: item.title, tone: item.tone, timestamp: item.timestamp, children: item.details.length > 0 ? <ul className="space-y-0.5">{item.details.map((d) => <li key={d.label}><span className="text-muted">{d.label}:</span> {d.value}</li>)}</ul> : undefined }))} />
      </section>

      {showRetry ? (
        <section className="rounded-3xl border border-border bg-card shadow-card p-6">
          <h2 className="text-base font-semibold text-heading">Çıkarımı yeniden dene</h2>
          <p className="mt-2 text-sm text-muted">
            Çıkarım takılı görünüyorsa yeniden tetikleyebilirsiniz. Yalnız işlem yöneticisi
            tetikleyebilir; yetkiniz yoksa aşağıda açıklama görürsünüz.
          </p>
          <button
            type="button"
            className="mt-4 rounded-2xl border border-border px-4 py-2 text-sm font-semibold text-heading transition hover:bg-primary-soft"
            onClick={() => setDialogOpen(true)}
            disabled={retrying}
          >
            Extraction'ı yeniden dene
          </button>
          {retryResult ? (
            <Notice tone="success">
              Yeniden çalıştırıldı — iş durumu: {retryResult.job_status ?? "—"}, deneme:{" "}
              {retryResult.attempt_count ?? "—"}.
            </Notice>
          ) : null}
          {retryError ? (
            retryError.kind === "permission_denied" ? (
              <div className="mt-3">
                <Notice tone="warning">Yalnız işlem yöneticisi tetikleyebilir.</Notice>
              </div>
            ) : retryError.kind === "conflict" ? (
              <div className="mt-3">
                <Notice tone="info">
                  Yeniden deneme zaten sürüyor. Tekrar denemek yerine sayfayı yenileyin.
                </Notice>
              </div>
            ) : (
              <div className="mt-3">
                <FormError error={retryError} />
              </div>
            )
          ) : null}
        </section>
      ) : null}

      {extraction ? (
        <section className="space-y-4">
          <h2 className="text-base font-semibold text-heading">Sözleşme ayrıntıları</h2>

          <div>
            <h3 className="mb-2 text-sm font-medium text-body">Mal / hizmet kalemleri</h3>
            <ResponsiveTable
              caption="Mal kalemleri"
              head={["Kalem", "Miktar", "Birim"]}
              emptyLabel="Kalem bilgisi yok"
              rows={extraction.commercial_terms.goods.map((g, i) => ({
                key: `${g.name}-${i}`,
                cells: [g.name, g.quantity, g.unit],
              }))}
            />
          </div>

          <div>
            <h3 className="mb-2 text-sm font-medium text-body">Ödeme kuralları</h3>
            <ResponsiveTable
              caption="Ödeme kuralları"
              head={["Aşama", "Tetikleyici", "Yüzde", "Gerekli kanıt", "Güven"]}
              emptyLabel="Ödeme kuralı yok"
              rows={extraction.payment_rules.map((rule, i) => ({
                key: `${rule.milestone}-${i}`,
                cells: [
                  rule.milestone,
                  rule.trigger,
                  `%${rule.percentage}`,
                  rule.required_evidence.join(", ") || "—",
                  formatRatioPercent(rule.confidence),
                ],
              }))}
            />
          </div>

          {extraction.risk_flags.length > 0 ? (
            <div>
              <h3 className="mb-2 text-sm font-medium text-body">Risk işaretleri</h3>
              <ul className="list-disc space-y-1 pl-5 text-sm text-amber-800">
                {extraction.risk_flags.map((flag) => (
                  <li key={flag}>{flag}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {extraction.needs_manual_review ? (
            <Notice tone="warning">Bu sözleşme için manuel inceleme öneriliyor.</Notice>
          ) : null}
        </section>
      ) : null}

      {validator ? (
        <section className="space-y-3">
          <div className="flex items-center gap-3">
            <h2 className="text-base font-semibold text-heading">Doğrulama</h2>
            <StatusBadge value={validator.status} map={validatorStatusMap} />
          </div>
          {validator.findings && validator.findings.length > 0 ? (
            <ul className="space-y-2">
              {validator.findings.map((finding, i) => (
                <li
                  key={`${finding.code}-${i}`}
                  className="rounded-2xl border border-border bg-subtle/60 p-3 text-sm"
                >
                  <span className="font-mono text-xs text-muted">{finding.code}</span>
                  <span className="ml-2 text-body">({finding.severity})</span>
                  {finding.message ? <p className="mt-1 text-body">{finding.message}</p> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Bulgu yok.</p>
          )}
        </section>
      ) : null}

      <ConfirmDialog
        open={dialogOpen}
        title="Çıkarımı yeniden dene"
        description="Sözleşme çıkarım hattı yeniden çalıştırılacak. Sağlayıcı/ödeme yan etkisi yoktur."
        confirmLabel="Yeniden dene"
        busy={retrying}
        onConfirm={() => void onConfirmRetry()}
        onCancel={() => setDialogOpen(false)}
      />
    </div>
  );
}
