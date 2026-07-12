import type { ReviewActionType, ReviewCase, ReviewCaseWithActions } from "../../../types/reviews";

// Review action payload'ından yalnız izinli, hassas olmayan anahtarlar gösterilir.
const ALLOWED_PAYLOAD_KEYS = [
  "comment",
  "resolution_code",
  "review_case_id",
  "instruction_id",
  "operation_type",
] as const;

export interface SafePayloadEntry {
  label: string;
  value: string;
}

export function safeActionPayloadEntries(
  payload: Record<string, unknown> | null,
): SafePayloadEntry[] {
  if (!payload) return [];
  const entries: SafePayloadEntry[] = [];
  for (const key of ALLOWED_PAYLOAD_KEYS) {
    if (!Object.prototype.hasOwnProperty.call(payload, key)) continue;
    const raw = payload[key];
    if (typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean") {
      entries.push({ label: key, value: String(raw) });
    }
  }
  return entries;
}

/** Review case'leri source_type'a göre böler (party_mismatch ayrıştırma için). */
export function splitCasesBySource(cases: ReviewCaseWithActions[]): {
  partyMismatch: ReviewCase[];
  others: ReviewCaseWithActions[];
} {
  const partyMismatch: ReviewCase[] = [];
  const others: ReviewCaseWithActions[] = [];
  for (const item of cases) {
    if (item.case.source_type === "party_mismatch") {
      partyMismatch.push(item.case);
    }
    others.push(item);
  }
  return { partyMismatch, others };
}

/** Review action 409/403/400 kodlarını Türkçe mesaja çevirir (C2). */
export function reviewActionErrorMessage(code: string): string {
  switch (code) {
    case "REVIEW_COMMENT_REJECTED":
      return "Yorum reddedildi: hassas veya token benzeri içerik olabilir.";
    case "REVIEW_ACTION_FORBIDDEN":
      return "Bu review aksiyonunu yapmaya yetkiniz yok.";
    case "REVIEW_CASE_NOT_FOUND":
      return "İnceleme kaydı bulunamadı.";
    case "REVIEW_CASE_CLOSED":
      return "İnceleme kaydı kapalı; yeni aksiyon eklenemez.";
    case "REVIEW_ACTION_NOT_ALLOWED":
      return "Bu aksiyon bu inceleme durumunda uygulanamaz.";
    case "REVIEW_RESOLUTION_PRECONDITION_FAILED":
      return "Çözüm ön koşulu sağlanmadı (örn. ödeme sonucu henüz kesinleşmedi).";
    default:
      return "İşlem tamamlanamadı. Verileri yenileyip tekrar deneyin.";
  }
}

/** Çözüm kodu isteyen aksiyonlar. */
const RESOLVE_ACTIONS: ReviewActionType[] = ["resolve_continue", "resolve_reject"];

export function isResolveAction(action: ReviewActionType): boolean {
  return RESOLVE_ACTIONS.includes(action);
}

export const REVIEW_ACTION_LABELS: Record<ReviewActionType, string> = {
  comment: "Yorum ekle",
  request_evidence: "Kanıt iste",
  resolve_continue: "Çöz ve devam et",
  resolve_reject: "Çöz ve reddet",
  escalate: "Yükselt",
  escalate_dispute: "Uyuşmazlığa taşı",
  cancel: "İptal et",
};
