import type { RatificationPackagePublicView } from "../../../types/ratification";
import { RatifyPanel } from "./RatifyPanel";

export function RatifyStep({ pkg, actingEntityName, busy, error, resultMessage, onRatify }: { pkg: RatificationPackagePublicView | null; actingEntityName: string; busy: boolean; error: string | null; resultMessage: string | null; onRatify: () => void; }) {
  const approved = Number(Boolean(pkg?.ratifications.buyer?.ratified)) + Number(Boolean(pkg?.ratifications.seller?.ratified));
  return <section className="card-surface space-y-4 p-5 sm:p-6"><header className="flex items-center justify-between gap-3"><div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-full bg-primary text-sm font-bold text-white">3</span><div><h2 className="text-lg font-bold text-heading">Taraflar onaylasın</h2><p className="text-sm text-muted">Her iki taraf aynı canonical paket hash’ini onaylar.</p></div></div><strong className="text-2xl font-bold text-primary">{approved}/2</strong></header><RatifyPanel pkg={pkg} actingEntityName={actingEntityName} busy={busy} error={error} resultMessage={resultMessage} onRatify={onRatify} /></section>;
}
