import { useState } from "react";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { KeyValueGrid, Notice } from "../../../components/Feedback";
import { formatDateTime } from "../../../lib/format";
import type { RatificationPackagePublicView } from "../../../types/ratification";
import { buttonClass } from "../../shared";

export function RatifyPanel({ pkg, actingEntityName, busy, error, resultMessage, onRatify }: { pkg: RatificationPackagePublicView | null; actingEntityName: string; busy: boolean; error: string | null; resultMessage: string | null; onRatify: () => void }) {
  const [open, setOpen] = useState(false);
  if (!pkg) return <Notice tone="info">Onay için önce paket oluşturulmalıdır.</Notice>;
  const progress = pkg.ratifications;
  const canRatify = pkg.status === "open";
  return <div className="space-y-4">
    <KeyValueGrid items={[
      { label: "İşlem yapan tüzel kişi", value: actingEntityName || "Tüzel kişi seçilmedi" },
      { label: "Alıcı onayı", value: progress.buyer?.ratified ? `Onaylandı · ${formatDateTime(progress.buyer.approved_at)}` : "Bekliyor" },
      { label: "Satıcı onayı", value: progress.seller?.ratified ? `Onaylandı · ${formatDateTime(progress.seller.approved_at)}` : "Bekliyor" },
    ]} />
    <p className="text-sm text-slate-300">{Number(progress.buyer?.ratified) + Number(progress.seller?.ratified)}/2 taraf onayladı.</p>
    {resultMessage ? <Notice tone="success">{resultMessage}</Notice> : null}{error ? <Notice tone="danger">{error}</Notice> : null}
    {!canRatify ? <Notice tone="info">Paket onaya açık değil ({pkg.status}).</Notice> : <button className={buttonClass} type="button" disabled={busy} onClick={() => setOpen(true)}>Paketi onayla</button>}
    <ConfirmDialog open={open} title="Paketi onayla" description={`“Onayla” hukuki taahhüt niteliğindedir; paket hash'i: ${pkg.package_hash}`} confirmLabel="Onayla" tone="danger" busy={busy} onCancel={() => setOpen(false)} onConfirm={() => { setOpen(false); onRatify(); }} />
  </div>;
}
