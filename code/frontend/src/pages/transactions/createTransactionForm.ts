import type { ParticipantRole } from "../../types/participants";

export interface CreateTransactionInput {
  file: File | null;
  actingEntityId: string | null;
  ownRole: ParticipantRole;
  counterpartyEmail: string;
}

export type CreateTransactionFormResult =
  | { ok: true; form: FormData }
  | { ok: false; error: string };

const ROLES: ParticipantRole[] = ["buyer", "seller"];

/**
 * Tipli girdiden multipart FormData üretir. İstemci tarafı yalnız dosya
 * varlığını ve rol geçerliliğini kontrol eder; suffix hatası backend 400'den
 * gelir (C1). Entity seçili değilse form gönderilemez.
 */
export function buildCreateTransactionForm(
  input: CreateTransactionInput,
): CreateTransactionFormResult {
  if (!input.actingEntityId) {
    return { ok: false, error: "Önce işlem yapılacak entity'yi seçin." };
  }
  if (!input.file) {
    return { ok: false, error: "Sözleşme dosyası seçin." };
  }
  if (!ROLES.includes(input.ownRole)) {
    return { ok: false, error: "Geçersiz rol." };
  }

  const form = new FormData();
  form.append("file", input.file);
  form.append("acting_entity_id", input.actingEntityId);
  form.append("own_role", input.ownRole);
  const email = input.counterpartyEmail.trim();
  if (email) {
    form.append("counterparty_email", email);
  }
  return { ok: true, form };
}

/** Ağ hatasında gösterilecek kör-tekrar önleyici uyarı (C1: idempotent değil). */
export const CREATE_NETWORK_WARNING =
  "İstek sunucuya ulaşmadan kesilmiş olabilir. İşlemi tekrar göndermeden önce " +
  "İşlemler listesini kontrol edin — kayıt oluşmuş olabilir.";

/** 422 alan-eksikliği kodlarını Türkçe mesaja çevirir. */
export function createFieldErrorMessage(code: string): string | null {
  switch (code) {
    case "ACCOUNT_CREATE_FIELDS_REQUIRED":
      return "İşlem oluşturmak için gerekli alanlar eksik.";
    case "INVALID_OWN_ROLE":
      return "Rol geçersiz; alıcı veya satıcı seçin.";
    default:
      return null;
  }
}
