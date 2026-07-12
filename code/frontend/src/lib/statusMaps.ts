export type StatusTone = "info" | "success" | "warning" | "danger" | "neutral";

export interface StatusDescriptor {
  label: string;
  tone: StatusTone;
}

export type StatusMap = Record<string, StatusDescriptor>;

/**
 * Bilinen bir statüyü çözer; harita dışı değeri nötr tonlu ham etiket olarak
 * döndürür (bilinmeyen backend state'i crash yerine görünür kılar).
 */
export function resolveStatus(map: StatusMap, value: string | null | undefined): StatusDescriptor {
  if (value && Object.prototype.hasOwnProperty.call(map, value)) {
    return map[value];
  }
  return { label: value ?? "—", tone: "neutral" };
}

/** account_v2 transaction state → rozet. */
export const transactionStateMap: StatusMap = {
  preparation: { label: "Hazırlık", tone: "info" },
  uploaded: { label: "İşleniyor", tone: "info" },
  extracting: { label: "İşleniyor", tone: "info" },
  awaiting_review: { label: "Manuel inceleme bekliyor", tone: "warning" },
  awaiting_approval: { label: "Onay hazırlığı", tone: "info" },
  awaiting_ratification: { label: "Taraf onayı bekleniyor", tone: "info" },
  funding_pending: { label: "Fonlama bekliyor", tone: "warning" },
  active: { label: "Aktif", tone: "success" },
  settled: { label: "Tamamlandı", tone: "success" },
  rejected: { label: "Reddedildi", tone: "danger" },
  cancelled: { label: "İptal", tone: "neutral" },
};

export const participantStatusMap: StatusMap = {
  invited: { label: "Davet edildi", tone: "info" },
  profile_incomplete: { label: "Profil eksik", tone: "warning" },
  ready: { label: "Hazır", tone: "info" },
  confirmed: { label: "Onaylandı", tone: "success" },
};

export const validatorStatusMap: StatusMap = {
  PASS: { label: "Geçti", tone: "success" },
  NEEDS_REVIEW: { label: "İnceleme gerekli", tone: "warning" },
  REJECT: { label: "Reddedildi", tone: "danger" },
};
