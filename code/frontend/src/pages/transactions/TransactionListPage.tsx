import { Link } from "react-router-dom";
import { listTransactions } from "../../api/transactions";
import { EmptyState, LoadingPanel, Notice, PageHeading, RetryPanel } from "../../components/Feedback";
import { MiniLifecycleStepper } from "../../components/LifecycleStepper";
import { StatusBadge } from "../../components/StatusBadge";
import { useEntities } from "../../entities/EntityContext";
import { formatDateTime, shortId } from "../../lib/format";
import { lifecycleFor, transactionStateMap } from "../../lib/lifecycle";
import { useAsyncData } from "../../lib/useAsyncData";
import { buttonClass } from "../shared";
import { groupTransactionsByState, transactionStats } from "./listProjection";

function StatIcon({ kind }: { kind: "total" | "active" | "action" | "settled" }) {
  const path = kind === "total" ? "M4 6h16M4 12h16M4 18h10" : kind === "active" ? "M12 3v18m9-9H3" : kind === "action" ? "M12 9v4m0 4h.01M10.3 3.7 2.8 17a2 2 0 0 0 1.7 3h15a2 2 0 0 0 1.7-3L13.7 3.7a2 2 0 0 0-3.4 0Z" : "m5 12 4 4L19 6";
  return <span className="grid size-10 place-items-center rounded-2xl bg-primary-soft text-primary"><svg aria-hidden="true" viewBox="0 0 24 24" className="size-5 fill-none stroke-current stroke-2" strokeLinecap="round" strokeLinejoin="round"><path d={path} /></svg></span>;
}

export function TransactionListPage() {
  const { selectedEntity, selectedEntityId, loading: entitiesLoading } = useEntities();
  const { data, loading, error, refresh } = useAsyncData(() => listTransactions(), [selectedEntityId], Boolean(selectedEntityId));
  const stats = transactionStats(data ?? []);
  const groups = groupTransactionsByState(data ?? []);
  const statCards = [
    { kind: "total" as const, label: "Toplam işlem", value: stats.total, delta: "Portföy görünümü" },
    { kind: "active" as const, label: "Aktif", value: stats.active, delta: "Teslimat aşamasında" },
    { kind: "action" as const, label: "Aksiyon bekliyor", value: stats.awaitingAction, delta: "Öncelikli takip" },
    { kind: "settled" as const, label: "Tamamlanan", value: stats.settled, delta: "Başarılı kapanış" },
  ];

  return <>
    <PageHeading eyebrow="İşlemler" title="İşlemleriniz" description="Yalnızca taraf veya yönetici olduğunuz işlemler listelenir." />
    <div className="mb-6 flex flex-wrap items-center gap-3"><Link className={buttonClass} to="/transactions/new">Yeni işlem</Link><button type="button" className="text-sm font-semibold text-primary hover:text-primary-hover disabled:opacity-50" onClick={() => void refresh()} disabled={loading}>Yenile</button></div>
    {!selectedEntity && !entitiesLoading ? <Notice tone="warning">İşlemleri listelemek için üst menüden bir entity seçin.</Notice> : null}
    {entitiesLoading && !selectedEntity ? <LoadingPanel label="İşlem yapılan entity yükleniyor…" /> : !selectedEntity ? null : loading && !data ? <LoadingPanel label="İşlemler yükleniyor…" /> : error ? <RetryPanel title="İşlemler yüklenemedi" message={error.userMessage} retrying={loading} onRetry={() => void refresh()} /> : !data || data.length === 0 ? <EmptyState title="Henüz işlem yok" description="İlk işleminizi oluşturarak sözleşme yükleyin ve karşı tarafı davet edin." action={<Link className={buttonClass} to="/transactions/new">Yeni işlem oluştur</Link>} /> : <div className="space-y-8">
      <section aria-label="İşlem istatistikleri" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{statCards.map((stat) => <article key={stat.label} className="card-surface p-5"><div className="flex items-center gap-3"><StatIcon kind={stat.kind} /><p className="text-sm font-semibold text-muted">{stat.label}</p></div><div className="mt-5 flex items-end justify-between gap-3"><strong className="text-4xl font-bold tracking-tight text-heading">{stat.value}</strong><span className="text-right text-xs font-bold text-positive">{stat.delta}</span></div></article>)}</section>
      <div className="space-y-7">{groups.map((group) => <section key={group.key} aria-labelledby={`group-${group.key}`}><div className="mb-3 flex items-center gap-3"><h2 id={`group-${group.key}`} className="text-lg font-bold text-heading">{group.label}</h2><span className="rounded-full bg-subtle px-2.5 py-1 text-xs font-bold text-muted">{group.transactions.length}</span></div><ul className="space-y-3">{group.transactions.map((tx) => { const lifecycle = lifecycleFor(tx.state); return <li key={tx.id}><Link to={`/transactions/${tx.id}/overview`} className="card-surface grid gap-4 p-4 transition hover:-translate-y-0.5 hover:border-primary/30 sm:grid-cols-[minmax(0,1.25fr)_minmax(12rem,1fr)_auto] sm:items-center"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-sm font-bold text-primary">{shortId(tx.id)}</span><StatusBadge value={tx.state} map={transactionStateMap} /></div><p className="mt-2 truncate text-sm font-semibold text-heading">{tx.buyer_name ?? "—"} → {tx.seller_name ?? "—"}</p><p className="mt-1 text-xs text-muted">{formatDateTime(tx.created_at)}</p></div><MiniLifecycleStepper lifecycle={lifecycle} /><span className="inline-flex items-center gap-1 text-sm font-bold text-primary">Aç <svg aria-hidden="true" viewBox="0 0 20 20" className="size-4 fill-none stroke-current stroke-2" strokeLinecap="round" strokeLinejoin="round"><path d="m7 4 6 6-6 6" /></svg></span></Link></li>; })}</ul></section>)}</div>
    </div>}
  </>;
}
