import { Link } from "react-router-dom";

import { listTransactions } from "../../api/transactions";
import { EmptyState, LoadingPanel, PageHeading, RetryPanel } from "../../components/Feedback";
import { ResponsiveTable } from "../../components/ResponsiveTable";
import { StatusBadge } from "../../components/StatusBadge";
import { formatDateTime, shortId } from "../../lib/format";
import { transactionStateMap } from "../../lib/statusMaps";
import { useAsyncData } from "../../lib/useAsyncData";
import { buttonClass } from "../shared";

export function TransactionListPage() {
  const { data, loading, error, refresh } = useAsyncData(() => listTransactions(), []);

  return (
    <>
      <PageHeading
        eyebrow="İşlemler"
        title="İşlemleriniz"
        description="Yalnızca taraf veya yönetici olduğunuz işlemler listelenir."
      />
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <Link className={buttonClass} to="/transactions/new">
          Yeni işlem
        </Link>
        <button
          type="button"
          className="text-sm font-medium text-cyan-300 hover:text-cyan-200 disabled:opacity-50"
          onClick={() => void refresh()}
          disabled={loading}
        >
          Yenile
        </button>
      </div>

      {loading && !data ? (
        <LoadingPanel label="İşlemler yükleniyor…" />
      ) : error ? (
        <RetryPanel
          title="İşlemler yüklenemedi"
          message={error.userMessage}
          retrying={loading}
          onRetry={() => void refresh()}
        />
      ) : !data || data.length === 0 ? (
        <EmptyState
          title="Henüz işlem yok"
          description="İlk işleminizi oluşturarak sözleşme yükleyin ve karşı tarafı davet edin."
          action={
            <Link className={buttonClass} to="/transactions/new">
              Yeni işlem oluştur
            </Link>
          }
        />
      ) : (
        <>
          {/* ≥640px: tablo */}
          <div className="hidden sm:block">
            <ResponsiveTable
              caption="İşlem listesi"
              head={["İşlem", "Durum", "Alıcı", "Satıcı", "Oluşturma"]}
              emptyLabel="Henüz işlem yok"
              rows={data.map((tx) => ({
                key: tx.id,
                cells: [
                  <Link
                    key="id"
                    className="font-mono text-cyan-300 hover:text-cyan-200"
                    to={`/transactions/${tx.id}/overview`}
                  >
                    {shortId(tx.id)}
                  </Link>,
                  <StatusBadge key="state" value={tx.state} map={transactionStateMap} />,
                  tx.buyer_name ?? "—",
                  tx.seller_name ?? "—",
                  formatDateTime(tx.created_at),
                ],
              }))}
            />
          </div>
          {/* <640px: kart listesi */}
          <ul className="space-y-3 sm:hidden">
            {data.map((tx) => (
              <li key={tx.id}>
                <Link
                  to={`/transactions/${tx.id}/overview`}
                  className="block rounded-2xl border border-white/10 bg-white/5 p-4 transition hover:bg-white/10"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-sm text-cyan-300">{shortId(tx.id)}</span>
                    <StatusBadge value={tx.state} map={transactionStateMap} />
                  </div>
                  <p className="mt-2 text-sm text-white">
                    {tx.buyer_name ?? "—"} → {tx.seller_name ?? "—"}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">{formatDateTime(tx.created_at)}</p>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
