import { Link, Outlet, useOutletContext, useParams } from "react-router-dom";

import { getTransaction } from "../api/transactions";
import { EmptyState, LoadingPanel, Notice, PageHeading } from "./Feedback";
import { SectionNav, type SectionNavItem } from "./SectionNav";
import { StatusBadge } from "./StatusBadge";
import { formatDateTime, shortId } from "../lib/format";
import { transactionStateMap } from "../lib/statusMaps";
import { useAsyncData } from "../lib/useAsyncData";
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
];

export interface TransactionShellContext {
  detail: TransactionDetail;
  refresh: () => Promise<void>;
  loading: boolean;
  error: ApiClientError | null;
}

/** Section sayfaları bu tiplenmiş yardımcıyla shell context'ine erişir. */
export function useTransactionShell(): TransactionShellContext {
  return useOutletContext<TransactionShellContext>();
}

export function TransactionShell() {
  const { transactionId } = useParams<{ transactionId: string }>();
  const id = transactionId ?? "";
  const { data, loading, error, refresh } = useAsyncData(() => getTransaction(id), [id]);

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
            <Link className="text-sm font-medium text-cyan-300 hover:text-cyan-200" to="/transactions">
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
          <Link className="text-sm font-medium text-cyan-300 hover:text-cyan-200" to="/transactions">
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

  const context: TransactionShellContext = { detail: data, refresh, loading, error };

  return (
    <>
      <PageHeading
        eyebrow={`İşlem ${shortId(data.id)}`}
        title="İşlem detayı"
        description={`Oluşturma: ${formatDateTime(data.created_at)}`}
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <StatusBadge value={data.state} map={transactionStateMap} />
        <span className="font-mono text-xs text-slate-500">{data.id}</span>
      </div>
      <SectionNav sections={SECTIONS} basePath={`/transactions/${data.id}`} />
      <div className="mt-6">
        <Outlet context={context} />
      </div>
    </>
  );
}
