import { useState } from "react";

import { createInvitation, listInvitations, reissueInvitation, revokeInvitation } from "../../api/invitations";
import {
  confirmMyProfile,
  listParticipants,
  updateMyProfile,
} from "../../api/participants";
import { ApiClientError, toApiClientError } from "../../api/client";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { LoadingPanel, Notice, RetryPanel, SkeletonRows } from "../../components/Feedback";
import { ResponsiveTable } from "../../components/ResponsiveTable";
import { StatusBadge } from "../../components/StatusBadge";
import { useTransactionShell } from "../../components/TransactionShell";
import { formatDateTime } from "../../lib/format";
import { extractInvitationToken, frontendInvitationPath } from "../../lib/inviteLink";
import { participantStatusMap } from "../../lib/statusMaps";
import { useAsyncData } from "../../lib/useAsyncData";
import type {
  InvitationCreateResult,
  Participant,
  ParticipantRole,
} from "../../types/participants";
import { buttonClass, FormError, inputClass, secondaryButtonClass } from "../shared";
import {
  invitableRoles,
  inviteErrorMessage,
  profilePanelMode,
  profileSnapshotFromForm,
} from "./partiesLogic";

const EMPTY_FORM = { name: "", tax_id: "", contact_email: "", contact_phone: "", address: "" };

export function TransactionPartiesPage() {
  const { detail, refresh: refreshShell } = useTransactionShell();
  const {
    data: participants,
    loading,
    error,
    refresh: refreshParticipants,
  } = useAsyncData(() => listParticipants(detail.id), [detail.id]);
  const { data: invitations, loading: invitationsLoading, error: invitationsError, refresh: refreshInvitations } = useAsyncData(() => listInvitations(detail.id), [detail.id]);

  // Davet paneli (B4: davet listesi endpoint'i yok — son create cevabı state'te tutulur).
  const [inviteRole, setInviteRole] = useState<ParticipantRole>("seller");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [lastInvite, setLastInvite] = useState<InvitationCreateResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [revokeDialog, setRevokeDialog] = useState(false);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [reissueBusy, setReissueBusy] = useState<string | null>(null);

  // Profil paneli.
  const [form, setForm] = useState(EMPTY_FORM);
  const [ownParticipant, setOwnParticipant] = useState<Participant | null>(null);
  const [profileError, setProfileError] = useState<ApiClientError | null>(null);
  const [profileNotice, setProfileNotice] = useState<string | null>(null);
  const [profileMissing, setProfileMissing] = useState(false);
  const [profileBusy, setProfileBusy] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState(false);
  const [overwriteDialog, setOverwriteDialog] = useState(false);

  const roles = participants ? invitableRoles(participants) : [];

  async function onCreateInvite(event: React.FormEvent) {
    event.preventDefault();
    setInviteError(null);
    setInviteBusy(true);
    try {
      const result = await createInvitation(detail.id, {
        participant_role: inviteRole,
        invited_email: inviteEmail.trim(),
      });
      setLastInvite(result);
      setInviteEmail("");
      await refreshParticipants();
      await refreshShell();
    } catch (caught) {
      setInviteError(inviteErrorMessage(toApiClientError(caught).code));
    } finally {
      setInviteBusy(false);
    }
  }

  async function onRevoke() {
    if (!lastInvite) return;
    setRevokeBusy(true);
    setInviteError(null);
    try {
      await revokeInvitation(detail.id, lastInvite.invitation_id);
      setLastInvite(null);
      setRevokeDialog(false);
      await refreshParticipants();
    } catch (caught) {
      setInviteError(inviteErrorMessage(toApiClientError(caught).code));
      setRevokeDialog(false);
    } finally {
      setRevokeBusy(false);
    }
  }

  async function onReissue(invitationId: string) {
    setReissueBusy(invitationId); setInviteError(null);
    try { const result = await reissueInvitation(detail.id, invitationId); setLastInvite(result); await refreshInvitations(); }
    catch (caught) { setInviteError(inviteErrorMessage(toApiClientError(caught).code)); }
    finally { setReissueBusy(null); }
  }

  async function submitProfile() {
    setProfileError(null);
    setProfileNotice(null);
    setProfileBusy(true);
    try {
      const updated = await updateMyProfile(detail.id, {
        snapshot: profileSnapshotFromForm(form),
      });
      setOwnParticipant(updated);
      setProfileMissing(false);
      setProfileNotice("Profil kaydedildi.");
    } catch (caught) {
      const err = toApiClientError(caught);
      if (err.status === 404) {
        setProfileMissing(true);
      } else {
        setProfileError(err);
      }
    } finally {
      setProfileBusy(false);
      setOverwriteDialog(false);
    }
  }

  async function onConfirmProfile() {
    setProfileError(null);
    setProfileNotice(null);
    setProfileBusy(true);
    try {
      const confirmed = await confirmMyProfile(detail.id);
      setOwnParticipant(confirmed);
      setProfileNotice(
        "Profil onaylandı; olası uyuşmazlık incelemesi kural bölümünde görünecek.",
      );
      await refreshParticipants();
      await refreshShell();
    } catch (caught) {
      const err = toApiClientError(caught);
      if (err.status === 404) {
        setProfileMissing(true);
      } else {
        setProfileError(err);
        // Çakışma: karşı taraf/güncel durum ile uyumsuz — yenile.
        if (err.kind === "conflict") await refreshParticipants();
      }
    } finally {
      setProfileBusy(false);
      setConfirmDialog(false);
    }
  }

  const ownStatus = ownParticipant?.status ?? null;
  const panelMode = profilePanelMode(ownStatus, ownParticipant != null, profileMissing);

  return (
    <div className="space-y-8">
      {/* Blok 1 — katılımcılar */}
      <section className="space-y-3">
        <h2 className="text-base font-semibold text-heading">Taraflar</h2>
        {loading && !participants ? (
          <LoadingPanel label="Taraflar yükleniyor…" />
        ) : error && !participants ? (
          <RetryPanel
            title="Taraflar yüklenemedi"
            message={error.userMessage}
            retrying={loading}
            onRetry={() => void refreshParticipants()}
          />
        ) : (
          <ResponsiveTable
            caption="Taraflar"
            head={["Rol", "Ad", "Durum", "Onay"]}
            emptyLabel="Taraf kaydı yok."
            rows={(participants ?? []).map((p) => ({
              key: p.id,
              cells: [
                p.role === "buyer" ? "Alıcı" : "Satıcı",
                p.display_name ?? "—",
                <StatusBadge key="s" value={p.status} map={participantStatusMap} />,
                p.confirmed_at ? formatDateTime(p.confirmed_at) : "—",
              ],
            }))}
          />
        )}
      </section>

      {/* Blok 2 — davet */}
      <section className="space-y-3 rounded-3xl border border-border bg-card shadow-card p-6">
        <h2 className="text-base font-semibold text-heading">Karşı tarafı davet et</h2>
        {roles.length === 0 ? (
          <Notice tone="info">Davet edilebilecek bekleyen bir rol yok.</Notice>
        ) : (
          <form className="flex flex-wrap items-end gap-3" onSubmit={onCreateInvite}>
            <label className="text-sm text-body">
              Rol
              <select
                className={`mt-1 block ${inputClass}`}
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value as ParticipantRole)}
              >
                {roles.map((role) => (
                  <option key={role} value={role}>
                    {role === "buyer" ? "Alıcı" : "Satıcı"}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex-1 text-sm text-body">
              E-posta
              <input
                type="email"
                required
                className={`mt-1 block ${inputClass}`}
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="karsitaraf@firma.com"
              />
            </label>
            <button type="submit" className={buttonClass} disabled={inviteBusy}>
              {inviteBusy ? "Gönderiliyor…" : "Davet gönder"}
            </button>
          </form>
        )}

        {inviteError ? <Notice tone="danger">{inviteError}</Notice> : null}

        {lastInvite ? (
          <div className="space-y-3 rounded-2xl border border-border bg-subtle/60 p-4">
            <Notice tone="warning">
              Bu bağlantı <strong>gizli ve tek kullanımlıktır</strong>. Yalnız davet ettiğiniz
              tarafla paylaşın.
            </Notice>
            {(() => {
              const token = extractInvitationToken(lastInvite.invite_link);
              return token ? (
                <div><p className="break-all font-mono text-sm text-primary">{frontendInvitationPath(token)}</p><button type="button" className={`mt-3 ${secondaryButtonClass}`} onClick={() => { void navigator.clipboard?.writeText(`${window.location.origin}${frontendInvitationPath(token)}`).then(() => setCopied(true)).catch(() => setCopied(false)); }}>{copied ? "Kopyalandı" : "Bağlantıyı kopyala"}</button></div>
              ) : null;
            })()}
            <p className="text-xs text-muted">
              Son geçerlilik: {formatDateTime(lastInvite.expires_at)}
            </p>
            <button
              type="button"
              className={secondaryButtonClass}
              onClick={() => setRevokeDialog(true)}
            >
              Daveti iptal et
            </button>
          </div>
        ) : (
          <Notice tone="info">
            Bekleyen daveti iptal etmek için aynı role yeni davet gönderin (eski davet otomatik
            geçersiz olur). Sayfa yenilendikten sonra davet kimliği görüntülenemez.
          </Notice>
        )}
      </section>

      {/* Blok 3 — kendi profilim */}
      <section className="space-y-3 rounded-3xl border border-border bg-card shadow-card p-6">
        <h2 className="text-base font-semibold text-heading">Profilim</h2>
        {panelMode === "hidden" ? (
          <Notice tone="info">
            Bu işlemde katılımcı kaydınız yok (görüntüleyici olabilirsiniz).
          </Notice>
        ) : (
          <>
            {panelMode === "overwrite_guard" ? (
              <Notice tone="warning">
                Daha önce kaydedilmiş profil bilgileriniz görüntülenemiyor (API sınırı). Formu
                göndermek önceki TÜM alanların üzerine yazar.
              </Notice>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2">
              {(
                [
                  ["name", "Ad / unvan", "text"],
                  ["tax_id", "Vergi/TCKN no", "text"],
                  ["contact_email", "İletişim e-postası", "email"],
                  ["contact_phone", "İletişim telefonu", "tel"],
                  ["address", "Adres", "text"],
                ] as const
              ).map(([key, label, type]) => (
                <label key={key} className="text-sm text-body">
                  {label}
                  <input
                    type={type}
                    className={`mt-1 ${inputClass}`}
                    value={form[key]}
                    onChange={(e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))}
                    disabled={profileBusy}
                  />
                </label>
              ))}
            </div>

            {profileNotice ? <Notice tone="success">{profileNotice}</Notice> : null}
            <FormError error={profileError} />

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                className={buttonClass}
                disabled={profileBusy || form.name.trim().length === 0}
                onClick={() =>
                  panelMode === "overwrite_guard" ? setOverwriteDialog(true) : void submitProfile()
                }
              >
                Profili kaydet
              </button>
              <button
                type="button"
                className={secondaryButtonClass}
                disabled={profileBusy || ownParticipant == null}
                onClick={() => setConfirmDialog(true)}
              >
                Profili onayla
              </button>
            </div>
            {ownParticipant == null ? (
              <p className="text-xs text-muted">
                Onaylamadan önce profili kaydedin (kaydetme cevabı gerekli).
              </p>
            ) : null}
          </>
        )}
      </section>

      <section className="space-y-3">
        <div><h2 className="text-base font-semibold text-heading">Davetler</h2><p className="mt-1 text-sm text-muted">Bağlantılar güvenlik nedeniyle listelenmez; yeniden oluşturulan bağlantı yalnız bir kez görünür.</p></div>
        {invitationsLoading && !invitations ? <SkeletonRows rows={3} /> : invitationsError && !invitations ? <RetryPanel title="Davetler yüklenemedi" message={invitationsError.userMessage} onRetry={() => void refreshInvitations()} /> : <ResponsiveTable caption="Davetler" head={["Kimlik", "Rol", "E-posta", "Durum", "İşlem"]} emptyLabel="Henüz davet yok." rows={(invitations ?? []).map((invitation) => ({ key: invitation.invitation_id, cells: [<span className="font-mono text-xs">{invitation.invitation_id}</span>, invitation.participant_role === "buyer" ? "Alıcı" : "Satıcı", invitation.invited_email, invitation.status, <button key="reissue" type="button" className={secondaryButtonClass} disabled={reissueBusy !== null || invitation.status === "accepted"} onClick={() => void onReissue(invitation.invitation_id)}>{reissueBusy === invitation.invitation_id ? "Oluşturuluyor…" : "Yeniden oluştur"}</button>] }))} />}
      </section>

      <ConfirmDialog
        open={revokeDialog}
        title="Daveti iptal et"
        description="Bu davet bağlantısı geçersiz kılınacak. Devam edilsin mi?"
        confirmLabel="İptal et"
        tone="danger"
        busy={revokeBusy}
        onConfirm={() => void onRevoke()}
        onCancel={() => setRevokeDialog(false)}
      />
      <ConfirmDialog
        open={overwriteDialog}
        title="Profilin üzerine yaz"
        description="Önceki profil bilgileriniz görüntülenemiyor. Devam ederseniz tüm alanlar bu formdaki değerlerle değiştirilir."
        confirmLabel="Üzerine yaz"
        tone="danger"
        busy={profileBusy}
        onConfirm={() => void submitProfile()}
        onCancel={() => setOverwriteDialog(false)}
      />
      <ConfirmDialog
        open={confirmDialog}
        title="Profili onayla"
        description="Onayladıktan sonra profil anlık görüntüsü dondurulur ve değiştirilemez."
        confirmLabel="Onayla"
        busy={profileBusy}
        onConfirm={() => void onConfirmProfile()}
        onCancel={() => setConfirmDialog(false)}
      />
    </div>
  );
}
