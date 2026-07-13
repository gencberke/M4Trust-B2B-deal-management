import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { acceptInvitation, previewInvitation } from "../api/invitations";
import { toApiClientError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, LoadingPanel, Notice, PageHeading } from "../components/Feedback";
import { useEntities } from "../entities/EntityContext";
import { useAsyncData } from "../lib/useAsyncData";
import type { ParticipantRole } from "../types/participants";
import { buttonClass, inputClass } from "./shared";
import { acceptErrorMessage, previewUnavailableMessage } from "./invitationLogic";

function roleLabel(role: ParticipantRole | string): string {
  if (role === "buyer") return "Alıcı";
  if (role === "seller") return "Satıcı";
  return role;
}

export function InvitationPage() {
  const { token } = useParams<{ token: string }>();
  const inviteToken = token ?? "";
  const navigate = useNavigate();
  const { user } = useAuth();
  const { entities, selectedEntityId } = useEntities();

  const { data, loading, error } = useAsyncData(
    () => previewInvitation(inviteToken),
    [inviteToken],
  );

  const [entityId, setEntityId] = useState<string>("");
  const [accepting, setAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);

  async function onAccept() {
    const chosen = entityId || selectedEntityId || "";
    if (!chosen) {
      setAcceptError("Önce bir tüzel/gerçek kişi seçin.");
      return;
    }
    setAccepting(true);
    setAcceptError(null);
    try {
      const participant = await acceptInvitation(inviteToken, { legal_entity_id: chosen });
      // Token geçmişten düşsün diye replace ile parties'e git.
      navigate(`/transactions/${participant.transaction_id}/parties`, { replace: true });
    } catch (caught) {
      const err = toApiClientError(caught);
      setAcceptError(acceptErrorMessage(err.code, err.status));
    } finally {
      setAccepting(false);
    }
  }

  if (loading) {
    return <LoadingPanel label="Davet yükleniyor…" />;
  }

  if (error || !data) {
    return (
      <>
        <PageHeading eyebrow="Davet" title="Davet" />
        <EmptyState
          title="Davet açılamadı"
          description={previewUnavailableMessage()}
          action={
            <Link className="text-sm font-medium text-primary hover:text-primary" to="/transactions">
              İşlemlere git
            </Link>
          }
        />
      </>
    );
  }

  return (
    <>
      <PageHeading eyebrow="Davet" title="İşleme davet edildiniz" />
      <div className="max-w-xl space-y-4">
        <div className="rounded-3xl border border-border bg-card shadow-card p-6">
          <p className="text-sm text-muted">Rol</p>
          <p className="mt-1 text-lg font-semibold text-heading">{roleLabel(data.participant_role)}</p>
          <p className="mt-4 text-sm text-muted">İşlem referansı</p>
          <p className="mt-1 font-mono text-sm text-primary">{data.transaction_reference}</p>
        </div>

        {!user ? (
          <div className="space-y-3 rounded-3xl border border-border bg-card shadow-card p-6">
            <Notice tone="info">
              Bu daveti kabul etmek için giriş yapmanız gerekiyor.
            </Notice>
            <p className="text-sm text-body">
              Giriş yaptıktan sonra bu davet bağlantısını yeniden açın.
            </p>
            <Link className={buttonClass} to="/login">
              Giriş yap
            </Link>
          </div>
        ) : (
          <div className="space-y-3 rounded-3xl border border-border bg-card shadow-card p-6">
            {entities.length === 0 ? (
              <Notice tone="warning">
                Daveti kabul etmek için önce bir tüzel/gerçek kişi profili oluşturun.{" "}
                <Link className="font-medium text-primary hover:text-primary" to="/entities/new">
                  Şirket ekle
                </Link>
              </Notice>
            ) : (
              <label className="block text-sm text-body">
                Hangi kişi/şirket adına kabul ediyorsunuz?
                <select
                  className={`mt-1 block ${inputClass}`}
                  value={entityId || selectedEntityId || ""}
                  onChange={(e) => setEntityId(e.target.value)}
                >
                  <option value="">Seçin…</option>
                  {entities.map((entity) => (
                    <option key={entity.id} value={entity.id}>
                      {entity.legal_name}
                    </option>
                  ))}
                </select>
              </label>
            )}

            {acceptError ? <Notice tone="danger">{acceptError}</Notice> : null}

            <button
              type="button"
              className={buttonClass}
              onClick={() => void onAccept()}
              disabled={accepting || entities.length === 0}
            >
              {accepting ? "Kabul ediliyor…" : "Daveti kabul et"}
            </button>
          </div>
        )}
      </div>
    </>
  );
}
