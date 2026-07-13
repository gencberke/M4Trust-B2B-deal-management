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

export const reviewStatusMap: StatusMap = {
  open: { label: "Açık", tone: "warning" },
  evidence_requested: { label: "Kanıt istendi", tone: "info" },
  resolved: { label: "Çözüldü", tone: "success" },
  escalated: { label: "Yükseltildi", tone: "danger" },
  cancelled: { label: "İptal", tone: "neutral" },
};

export const reviewSeverityMap: StatusMap = {
  warning: { label: "Uyarı", tone: "warning" },
  blocking: { label: "Engelleyici", tone: "danger" },
};

export const reviewPhaseMap: StatusMap = {
  pre_ratification: { label: "Onay öncesi", tone: "info" },
  settlement: { label: "Ödeme yürütme", tone: "info" },
  payment: { label: "Ödeme", tone: "info" },
};

export const reviewSourceMap: StatusMap = {
  validator: { label: "Doğrulama", tone: "info" },
  party_mismatch: { label: "Taraf uyuşmazlığı", tone: "warning" },
  evidence: { label: "Kanıt", tone: "info" },
  video: { label: "Video", tone: "info" },
  payment: { label: "Ödeme", tone: "info" },
  system: { label: "Sistem", tone: "neutral" },
};

export const packageStatusMap: StatusMap = {
  draft: { label: "Taslak", tone: "neutral" },
  open: { label: "Onaya açık", tone: "info" },
  complete: { label: "Tamamlandı", tone: "success" },
  superseded: { label: "Yenilendi", tone: "warning" },
  cancelled: { label: "İptal", tone: "neutral" },
};

export const policyStatusMap: StatusMap = {
  draft: { label: "Taslak", tone: "warning" },
  locked: { label: "Kilitli", tone: "success" },
};

export const ruleSetStatusMap: StatusMap = {
  draft: { label: "Taslak", tone: "neutral" },
  validated: { label: "Doğrulandı", tone: "info" },
  ratifiable: { label: "Onaya uygun", tone: "success" },
  superseded: { label: "Yenilendi", tone: "warning" },
  ratified: { label: "Onaylandı", tone: "success" },
};
