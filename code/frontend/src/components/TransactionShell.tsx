import { Link, Outlet, useOutletContext, useParams } from "react-router-dom";

import { getTransaction } from "../api/transactions";
import { EmptyState, LoadingPanel, Notice, PageHeading } from "./Feedback";
import { SectionNav, type SectionNavItem } from "./SectionNav";
import { StatusBadge } from "./StatusBadge";
import { LifecycleStepper } from "./LifecycleStepper";
import { formatDateTime, shortId } from "../lib/format";
import { inferLifecycleRole, lifecycleFor, lifecycleSectionState, transactionStateMap, type LifecycleDescriptor, type LifecycleRole } from "../lib/lifecycle";
import { useAsyncData } from "../lib/useAsyncData";
import { useEntities } from "../entities/EntityContext";
import type { ApiClientError } from "../api/client";
import type { TransactionDetail } from "../types/transactions";

// Bölüm kaydı — PR 2/3 buraya yeni slug ekler; kabuk aksi hâlde değişmez.
const SECTIONS: SectionNavItem[] = [
  { slug: "overview", label: "Genel bakış" },
  { slug: "parties", label: "Taraflar" },
  { slug: "rules", label: "Kurallar" },
  { slug: "ratification", label: "Onay" },
  { slug: "fulfillment", label: "Teslimat" },
  { slug: "disputes", label: "İtirazlar" },
  { slug: "payments", label: "Ödemeler" },
];

export interface TransactionShellContext {
  detail: TransactionDetail;
  refresh: () => Promise<void>;
  loading: boolean;
  error: ApiClientError | null;
  lifecycle: LifecycleDescriptor;
  lifecycleRole: LifecycleRole;
}

/** Section sayfaları bu tiplenmiş yardımcıyla shell context'ine erişir. */
export function useTransactionShell(): TransactionShellContext {
  return useOutletContext<TransactionShellContext>();
}

export function TransactionShell() {
  const { transactionId } = useParams<{ transactionId: string }>();
  const { selectedEntity, selectedEntityId, loading: entitiesLoading } = useEntities();
  const id = transactionId ?? "";
  const { data, loading, error, refresh } = useAsyncData(
    () => getTransaction(id),
    [id, selectedEntityId],
    Boolean(id && selectedEntityId),
  );

  if (entitiesLoading && !selectedEntity) {
    return <LoadingPanel label="İşlem yapılan entity yükleniyor…" />;
  }

  if (!selectedEntity) {
    return (
      <Notice tone="warning">
        İşlem ayrıntılarını görmek için üst menüden işlem yapılan entity'yi seçin.
      </Notice>
    );
  }

  if (loading && !data) {
    return <LoadingPanel label="İşlem yükleniyor…" />;
  }

  if (error && !data) {
    if (error.kind === "not_found") {
      return (
        <EmptyState
          title="İşlem bulunamadı"
          description="Bu işlem mevcut değil veya kaldırılmış olabilir."
          action={
            <Link className="text-sm font-medium text-primary hover:text-primary" to="/transactions">
              İşlemlere dön
            </Link>
          }
        />
      );
    }
    if (error.kind === "permission_denied") {
      return (
        <div className="space-y-4">
          <Notice tone="danger">Bu işlemde erişiminiz yok.</Notice>
          <Link className="text-sm font-medium text-primary hover:text-primary" to="/transactions">
            İşlemlere dön
          </Link>
        </div>
      );
    }
    // 401 zaten yönlendirme handler'ıyla ele alınır; diğerleri için genel panel.
    return <Notice tone="danger">{error.userMessage}</Notice>;
  }

  if (!data) {
    return <Notice tone="danger">İşlem yüklenemedi.</Notice>;
  }

  const lifecycleRole = inferLifecycleRole(selectedEntity.legal_name, data.extraction);
  const lifecycle = lifecycleFor(data.canonical_state ?? data.state, lifecycleRole);
  const context: TransactionShellContext = { detail: data, refresh, loading, error, lifecycle, lifecycleRole };

  return (
    <>
      <PageHeading
        eyebrow={`İşlem ${shortId(data.id)}`}
        title="İşlem detayı"
        description={`Oluşturma: ${formatDateTime(data.created_at)}`}
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <StatusBadge value={data.state} map={transactionStateMap} />
        <span className="font-mono text-xs text-muted">{data.id}</span>
        <span className="rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs text-primary">
          {selectedEntity.legal_name} adına
        </span>
      </div>
      <div className="mb-6 space-y-4">
        <LifecycleStepper lifecycle={lifecycle} />
      </div>
      <SectionNav sections={SECTIONS.map((section) => ({ ...section, ...lifecycleSectionState(section.slug, lifecycle) }))} basePath={`/transactions/${data.id}`} />
      <div className="mt-6">
        <Outlet key={selectedEntityId} context={context} />
      </div>
    </>
  );
}
