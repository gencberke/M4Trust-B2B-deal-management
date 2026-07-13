import { useState } from "react";
import { advanceDemoTransaction, type DemoTargetState } from "../api/demo";
import { toApiClientError } from "../api/client";
import { Notice } from "./Feedback";
import { buttonClass, secondaryButtonClass } from "../pages/shared";
import { listInvitations, reissueInvitation } from "../api/invitations";
import { useAsyncData } from "../lib/useAsyncData";
import { extractInvitationToken, frontendInvitationPath } from "../lib/inviteLink";
import type { InvitationCreateResult } from "../types/participants";

const TARGETS: { value: DemoTargetState; label: string }[] = [
  { value: "awaiting_ratification", label: "Onay bekliyor" }, { value: "active", label: "Aktif" },
  { value: "active_partial", label: "Kısmi teslimat" }, { value: "settled", label: "Kapandı" },
  { value: "disputed", label: "İtirazlı" }, { value: "awaiting_review", label: "İnceleme bekliyor" },
];

export function DemoPanel({ transactionId, onAdvanced }: { transactionId: string; onAdvanced: () => Promise<void> }) {
  const [target, setTarget] = useState<DemoTargetState>("active");
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState<string | null>(null); const [error, setError] = useState<string | null>(null);
  const { data: invitations, refresh: refreshInvitations } = useAsyncData(() => listInvitations(transactionId), [transactionId]);
  const [freshInvite, setFreshInvite] = useState<InvitationCreateResult | null>(null);
  async function advance() {
    setBusy(true); setError(null); setMessage(null);
    try { const result = await advanceDemoTransaction(transactionId, target); setMessage(`İşlem ${result.state ?? target} durumuna ilerletildi.`); await onAdvanced(); }
    catch (caught) { setError(toApiClientError(caught).userMessage); } finally { setBusy(false); }
  }
  async function reissue(invitationId: string) {
    setBusy(true); setError(null);
    try { setFreshInvite(await reissueInvitation(transactionId, invitationId)); await refreshInvitations(); }
    catch (caught) { setError(toApiClientError(caught).userMessage); } finally { setBusy(false); }
  }
  return <aside className="fixed bottom-5 right-5 z-30 w-[min(24rem,calc(100vw-2.5rem))] rounded-3xl border border-primary/25 bg-card p-5 shadow-xl">
    <div className="mb-3 flex items-center justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[0.16em] text-primary">Demo araçları</p><p className="mt-1 text-sm text-muted">Gerçek servis akışıyla ilerletin.</p></div><span className="rounded-full bg-primary-soft px-2 py-1 text-xs font-semibold text-primary">Yalnız demo</span></div>
    <div className="flex gap-2"><select className="min-w-0 flex-1 rounded-xl border border-border bg-card px-3 py-2 text-sm text-heading" value={target} onChange={(e) => setTarget(e.target.value as DemoTargetState)}>{TARGETS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><button className={buttonClass} disabled={busy} onClick={() => void advance()}>{busy ? "İlerliyor…" : "İleri al"}</button></div>
    {message ? <div className="mt-3"><Notice tone="success">{message}</Notice></div> : null}{error ? <div className="mt-3"><Notice tone="danger">{error}</Notice></div> : null}
    <div className="mt-4 border-t border-border pt-3"><p className="text-xs font-semibold text-heading">İşlem davetleri</p>{invitations?.length ? <ul className="mt-2 space-y-2">{invitations.map((invite) => <li key={invite.invitation_id} className="flex items-center justify-between gap-2 text-xs"><span className="truncate text-muted">{invite.participant_role} · {invite.invited_email} · {invite.status}</span><button className={secondaryButtonClass} disabled={busy || invite.status === "accepted"} onClick={() => void reissue(invite.invitation_id)}>Yenile</button></li>)}</ul> : <p className="mt-2 text-xs text-muted">Davet yok.</p>}</div>
    {freshInvite ? (() => { const token = extractInvitationToken(freshInvite.invite_link); const path = token ? frontendInvitationPath(token) : freshInvite.invite_link; return <div className="mt-3 rounded-xl bg-warning-soft p-3"><p className="break-all font-mono text-xs text-heading">{path}</p><button className={`mt-2 ${secondaryButtonClass}`} onClick={() => void navigator.clipboard?.writeText(token ? `${window.location.origin}${path}` : path)}>Kopyala</button></div>; })() : null}
    <a className="mt-3 inline-flex text-xs font-semibold text-primary" href={`/transactions/${transactionId}/parties`}>Tüm davetleri yönet</a>
  </aside>;
}
