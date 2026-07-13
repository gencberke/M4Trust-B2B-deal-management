import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { createTransaction } from "../../api/transactions";
import { Notice, PageHeading } from "../../components/Feedback";
import { useEntities } from "../../entities/EntityContext";
import { extractInvitationToken, frontendInvitationPath } from "../../lib/inviteLink";
import { ApiClientError, toApiClientError } from "../../api/client";
import type { CreateTransactionResponse } from "../../types/transactions";
import type { ParticipantRole } from "../../types/participants";
import { buttonClass, FormError, inputClass, secondaryButtonClass } from "../shared";
import {
  buildCreateTransactionForm,
  createFieldErrorMessage,
  CREATE_NETWORK_WARNING,
} from "./createTransactionForm";

const ACCEPT_SUFFIXES = ".pdf,.docx,.png,.jpg,.jpeg,.md,.txt";

export function TransactionCreatePage() {
  const navigate = useNavigate();
  const { selectedEntity, loading: entitiesLoading } = useEntities();
  const [file, setFile] = useState<File | null>(null);
  const [ownRole, setOwnRole] = useState<ParticipantRole>("buyer");
  const [counterpartyEmail, setCounterpartyEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<ApiClientError | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [networkWarning, setNetworkWarning] = useState(false);
  const [created, setCreated] = useState<CreateTransactionResponse | null>(null);
  const [copied, setCopied] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setValidationError(null);
    setFormError(null);
    setNetworkWarning(false);

    const built = buildCreateTransactionForm({
      file,
      actingEntityId: selectedEntity?.id ?? null,
      ownRole,
      counterpartyEmail,
    });
    if (!built.ok) {
      setValidationError(built.error);
      return;
    }

    setSubmitting(true);
    try {
      const response = await createTransaction(built.form);
      setCreated(response);
      if (!response.invitation) {
        navigate(`/transactions/${response.id}/overview`);
      }
    } catch (caught) {
      const error = toApiClientError(caught);
      if (error.kind === "network") {
        setNetworkWarning(true);
      } else {
        const fieldMessage = createFieldErrorMessage(error.code);
        setFormError(
          fieldMessage
            ? new ApiClientError({ kind: error.kind, code: error.code, userMessage: fieldMessage })
            : error,
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  // Başarılı + davetli: tek seferlik davet paneli.
  if (created?.invitation) {
    const token = extractInvitationToken(created.invitation.invite_link);
    return (
      <>
        <PageHeading eyebrow="İşlemler" title="İşlem oluşturuldu" />
        <div className="max-w-2xl space-y-4">
          <Notice tone="success">
            İşlem oluşturuldu. Karşı taraf için tek seferlik davet bağlantısı hazır.
          </Notice>
          <Notice tone="warning">
            Bu bağlantı <strong>gizli ve tek kullanımlıktır</strong>. Yalnız davet ettiğiniz karşı
            tarafla paylaşın; bir yerde saklamayın.
          </Notice>
          <Notice tone="info">Bağlantıyı kaybederseniz işlemin Taraflar sayfasından yeniden oluşturabilirsiniz.</Notice>
          {token ? (
            <div className="rounded-2xl border border-border bg-subtle/60 p-4">
              <p className="break-all font-mono text-sm text-primary">
                {frontendInvitationPath(token)}
              </p>
              <button
                type="button"
                className={`mt-3 ${secondaryButtonClass}`}
                onClick={() => {
                  void navigator.clipboard
                    ?.writeText(`${window.location.origin}${frontendInvitationPath(token)}`)
                    .then(() => setCopied(true))
                    .catch(() => setCopied(false));
                }}
              >
                {copied ? "Kopyalandı" : "Bağlantıyı kopyala"}
              </button>
            </div>
          ) : (
            <Notice tone="warning">Davet bağlantısı çözümlenemedi; parties bölümünden yeni davet gönderebilirsiniz.</Notice>
          )}
          <Link className={buttonClass} to={`/transactions/${created.id}/overview`}>
            İşleme git
          </Link>
        </div>
      </>
    );
  }

  const entityMissing = !selectedEntity;

  return (
    <>
      <PageHeading
        eyebrow="İşlemler"
        title="Yeni işlem"
        description="Sözleşmeyi yükleyin, rolünüzü seçin; karşı tarafı davet e-postasıyla çağırabilirsiniz."
      />
      <form className="max-w-2xl space-y-5" onSubmit={onSubmit}>
        {entitiesLoading ? (
          <Notice tone="info">Şirket bilgileri yükleniyor. Formu bu sırada doldurabilirsiniz.</Notice>
        ) : entityMissing ? (
          <Notice tone="warning">
            İşlemi oluşturmak için önce bir şirket ekleyin veya üst menüden işlem yapılacak
            şirketi seçin.{" "}
            <Link className="font-semibold underline" to="/entities/new">Şirket ekle</Link>
          </Notice>
        ) : (
          <Notice tone="info">
            İşlem şu entity adına oluşturulacak: <strong>{selectedEntity.legal_name}</strong>
          </Notice>
        )}

        <div>
          <label className="mb-2 block text-sm text-body" htmlFor="contract-file">
            Sözleşme dosyası
          </label>
          <input
            id="contract-file"
            type="file"
            accept={ACCEPT_SUFFIXES}
            className="block w-full text-sm text-body file:mr-4 file:rounded-xl file:border-0 file:bg-primary file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={submitting}
          />
          <p className="mt-1 text-xs text-muted">İzin verilen türler: pdf, docx, png, jpg, jpeg, md, txt.</p>
        </div>

        <fieldset disabled={submitting}>
          <legend className="mb-2 text-sm text-slate-300">Bu işlemdeki rolünüz</legend>
          <div className="flex gap-4">
            {(["buyer", "seller"] as ParticipantRole[]).map((role) => (
              <label key={role} className="flex items-center gap-2 text-sm text-heading">
                <input
                  type="radio"
                  name="own-role"
                  value={role}
                  checked={ownRole === role}
                  onChange={() => setOwnRole(role)}
                />
                {role === "buyer" ? "Alıcı" : "Satıcı"}
              </label>
            ))}
          </div>
        </fieldset>

        <div>
          <label className="mb-2 block text-sm text-body" htmlFor="counterparty-email">
            Karşı taraf e-postası (isteğe bağlı)
          </label>
          <input
            id="counterparty-email"
            type="email"
            className={inputClass}
            value={counterpartyEmail}
            onChange={(e) => setCounterpartyEmail(e.target.value)}
            disabled={submitting}
            placeholder="ornek@firma.com"
          />
          <p className="mt-1 text-xs text-muted">
            E-posta verilirse karşı taraf için davet bağlantısı üretilir.
          </p>
        </div>

        {validationError ? <Notice tone="danger">{validationError}</Notice> : null}
        {networkWarning ? <Notice tone="warning">{CREATE_NETWORK_WARNING}</Notice> : null}
        <FormError error={formError} />

        <button type="submit" className={buttonClass} disabled={submitting}>
          {submitting ? "Oluşturuluyor…" : "İşlemi oluştur"}
        </button>
      </form>
    </>
  );
}
