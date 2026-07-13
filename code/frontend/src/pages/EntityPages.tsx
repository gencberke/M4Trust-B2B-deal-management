import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { ApiClientError, apiRequest, toApiClientError } from "../api/client";
import { LoadingPanel, Notice, PageHeading } from "../components/Feedback";
import { useEntities } from "../entities/EntityContext";
import type {
  EntityCreateRequest,
  EntityPublic,
  EntityType,
  EntityUpdateRequest,
  TaxIdentifierType,
} from "../types/api";
import { buttonClass, FormError, Info, inputClass, parseAddress } from "./shared";

export function EntityCreatePage() {
  const { refreshEntities, selectEntity } = useEntities();
  const navigate = useNavigate();
  const [entityType, setEntityType] = useState<EntityType>("company");
  const [taxType, setTaxType] = useState<TaxIdentifierType>("vkn");
  const [legalName, setLegalName] = useState("");
  const [taxIdentifier, setTaxIdentifier] = useState("");
  const [taxOffice, setTaxOffice] = useState("");
  const [address, setAddress] = useState("");
  const [error, setError] = useState<ApiClientError | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setClientError(null);
    try {
      const body: EntityCreateRequest = {
        entity_type: entityType,
        legal_name: legalName,
        tax_identifier_type: taxType,
        tax_identifier: taxIdentifier,
        tax_office: taxOffice.trim() || null,
        address_json: parseAddress(address),
      };
      const created = await apiRequest<EntityPublic>("/entities", {
        method: "POST",
        csrf: true,
        body,
        redirectOnError: false,
      });
      await refreshEntities();
      selectEntity(created.id);
      navigate(`/entities/${created.id}`, { replace: true, state: { created: true } });
    } catch (caught) {
      if (caught instanceof SyntaxError || (caught instanceof Error && !(caught instanceof ApiClientError))) {
        setClientError("Adres alanı geçerli bir JSON nesnesi olmalıdır.");
      } else {
        setError(toApiClientError(caught));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeading title="Legal entity oluştur" description="Vergi kimliği yalnız oluşturma isteğinde gönderilir; profil ekranına backend’in maskeli son dört hanesi gelir." />
      <form className="space-y-4 rounded-3xl border border-border bg-card shadow-card p-6" onSubmit={submit}>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm text-body">Entity türü<select className={`${inputClass} mt-2`} value={entityType} onChange={(e) => setEntityType(e.target.value as EntityType)}><option value="company">Şirket</option><option value="individual">Gerçek kişi</option></select></label>
          <label className="text-sm text-body">Vergi kimliği türü<select className={`${inputClass} mt-2`} value={taxType} onChange={(e) => setTaxType(e.target.value as TaxIdentifierType)}><option value="vkn">VKN</option><option value="tckn">TCKN</option></select></label>
        </div>
        <input className={inputClass} required placeholder="Yasal unvan" value={legalName} onChange={(e) => setLegalName(e.target.value)} />
        <input className={inputClass} required inputMode="numeric" placeholder={taxType === "vkn" ? "10 haneli VKN" : "11 haneli TCKN"} value={taxIdentifier} onChange={(e) => setTaxIdentifier(e.target.value)} />
        <input className={inputClass} placeholder="Vergi dairesi · opsiyonel" value={taxOffice} onChange={(e) => setTaxOffice(e.target.value)} />
        <textarea className={`${inputClass} min-h-32 font-mono`} placeholder={'Adres JSON · örn. {"city":"İstanbul"}'} value={address} onChange={(e) => setAddress(e.target.value)} />
        {clientError ? <Notice tone="danger">{clientError}</Notice> : null}
        <FormError error={error} />
        <button className={buttonClass} disabled={submitting}>{submitting ? "Oluşturuluyor…" : "Entity oluştur"}</button>
      </form>
    </div>
  );
}

export function EntityProfilePage() {
  const { entityId } = useParams();
  const location = useLocation();
  const { refreshEntities } = useEntities();
  const [entity, setEntity] = useState<EntityPublic | null>(null);
  const [legalName, setLegalName] = useState("");
  const [taxOffice, setTaxOffice] = useState("");
  const [address, setAddress] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [saved, setSaved] = useState(Boolean((location.state as { created?: boolean } | null)?.created));

  useEffect(() => {
    if (!entityId) return;
    let active = true;
    setLoading(true);
    void apiRequest<EntityPublic>(`/entities/${entityId}`)
      .then((result) => {
        if (!active) return;
        setEntity(result);
        setLegalName(result.legal_name);
        setTaxOffice(result.tax_office ?? "");
        setAddress(result.address_json ? JSON.stringify(result.address_json, null, 2) : "");
      })
      .catch((caught) => {
        if (active) setError(toApiClientError(caught));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [entityId]);

  const canEdit = entity?.my_role === "owner" || entity?.my_role === "admin";
  const maskedTaxId = useMemo(
    () => (entity ? `${entity.tax_identifier_type.toUpperCase()} •••• ${entity.tax_identifier_last4}` : ""),
    [entity],
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!entityId || !canEdit) return;
    setSubmitting(true);
    setError(null);
    setClientError(null);
    setSaved(false);
    try {
      const body: EntityUpdateRequest = {
        legal_name: legalName,
        tax_office: taxOffice.trim() || null,
        address_json: parseAddress(address),
      };
      const updated = await apiRequest<EntityPublic>(`/entities/${entityId}`, {
        method: "PATCH",
        csrf: true,
        body,
        redirectOnError: false,
      });
      setEntity(updated);
      await refreshEntities();
      setSaved(true);
    } catch (caught) {
      if (caught instanceof SyntaxError || (caught instanceof Error && !(caught instanceof ApiClientError))) {
        setClientError("Adres alanı geçerli bir JSON nesnesi olmalıdır.");
      } else {
        setError(toApiClientError(caught));
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <LoadingPanel label="Entity profili yükleniyor…" />;
  if (!entity) return <FormError error={error} />;

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeading title="Entity profili" description="Yetki ve doğrulama durumu yalnız backend projection’ından okunur." />
      <form className="space-y-4 rounded-3xl border border-border bg-card shadow-card p-6" onSubmit={submit}>
        {saved ? <Notice tone="success">Profil bilgileri kaydedildi.</Notice> : null}
        {!canEdit ? <Notice tone="warning">Backend membership projection’ınıza göre bu profil salt okunurdur.</Notice> : null}
        <div className="rounded-2xl border border-border bg-surface/60 p-4">
          <p className="text-xs uppercase tracking-wide text-muted">Maskeli vergi kimliği</p>
          <p className="mt-2 font-mono text-lg text-heading">{maskedTaxId}</p>
        </div>
        <input className={inputClass} required disabled={!canEdit} value={legalName} onChange={(e) => setLegalName(e.target.value)} />
        <input className={inputClass} disabled={!canEdit} placeholder="Vergi dairesi" value={taxOffice} onChange={(e) => setTaxOffice(e.target.value)} />
        <textarea className={`${inputClass} min-h-32 font-mono`} disabled={!canEdit} placeholder="Adres JSON" value={address} onChange={(e) => setAddress(e.target.value)} />
        <dl className="grid gap-3 sm:grid-cols-2">
          <Info label="Membership rolü" value={entity.my_role} />
          <Info label="Doğrulama durumu" value={entity.verification_status} />
        </dl>
        {clientError ? <Notice tone="danger">{clientError}</Notice> : null}
        <FormError error={error} />
        {canEdit ? <button className={buttonClass} disabled={submitting}>{submitting ? "Kaydediliyor…" : "Profili güncelle"}</button> : null}
      </form>
    </div>
  );
}
