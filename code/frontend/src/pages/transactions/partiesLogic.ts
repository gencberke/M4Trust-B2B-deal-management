import type {
  ParticipantPublicView,
  ParticipantRole,
  ParticipantStatus,
  PartyProfileSnapshot,
} from "../../types/participants";

const ROLES: ParticipantRole[] = ["buyer", "seller"];

/**
 * Davet edilebilir roller: karşılık gelen katılımcı `invited` ve henüz
 * `confirmed` değilse. Aynı role yeni davet eskisini supersede eder (contract);
 * bu yüzden `invited` iken hâlâ teklif edilir.
 */
export function invitableRoles(participants: ParticipantPublicView[]): ParticipantRole[] {
  return ROLES.filter((role) =>
    participants.some((p) => p.role === role && p.status === "invited" && !p.confirmed),
  );
}

/** Form alanlarını normalize eder: trim, boş → null. `name` her zaman string. */
export function profileSnapshotFromForm(fields: {
  name: string;
  tax_id: string;
  contact_email: string;
  contact_phone: string;
  address: string;
}): PartyProfileSnapshot {
  const clean = (value: string): string | null => {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  };
  return {
    name: fields.name.trim(),
    tax_id: clean(fields.tax_id),
    contact_email: clean(fields.contact_email),
    contact_phone: clean(fields.contact_phone),
    address: clean(fields.address),
  };
}

/** Davet oluşturma/iptal hata kodlarını Türkçe mesaja çevirir. */
export function inviteErrorMessage(code: string): string {
  switch (code) {
    case "INVITATION_ROLE_ALREADY_BOUND":
      return "Bu rol zaten bir tarafa bağlı; yeni davet gönderilemez.";
    case "INVITATION_FORBIDDEN":
      return "Bu işlemde davet gönderme/iptal yetkiniz yok.";
    case "INVITATION_NOT_FOUND":
      return "Davet bulunamadı.";
    case "INVITATION_NOT_REVOCABLE":
      return "Bu davet artık iptal edilemez (kabul edilmiş, süresi dolmuş veya iptal edilmiş).";
    default:
      return "İşlem tamamlanamadı. Verileri yenileyip tekrar deneyin.";
  }
}

export type ProfilePanelMode = "editable" | "overwrite_guard" | "hidden";

/**
 * Profil panelinin gösterim modunu belirler. B9 (master §14.1): `GET
 * participants/me` yok — reload sonrası declared snapshot okunamaz. Yerel
 * snapshot yoksa ve public durum `ready` ise formu overwrite uyarısı arkasına al.
 */
export function profilePanelMode(
  ownStatus: ParticipantStatus | null,
  hasLocalSnapshot: boolean,
  participantMissing: boolean,
): ProfilePanelMode {
  if (participantMissing) return "hidden";
  if (!hasLocalSnapshot && ownStatus === "ready") return "overwrite_guard";
  return "editable";
}
