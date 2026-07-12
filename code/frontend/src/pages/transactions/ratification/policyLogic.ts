import type { PolicyConflictDetail } from "../../../types/tracking";

/**
 * Policy 409 gövdesi (`PolicyConflict`) genelde düz `HTTPException(detail={...})`
 * biçiminde döner ve merkezi client bunu envelope olarak tanımadığı için
 * `error.detail`'e yansıtmayabilir. Yine de detay geldiğinde tiplenmiş
 * çözümlemek için bu guard kullanılır (string veya obje toleranslı).
 */
export function parsePolicyConflict(detail: unknown): PolicyConflictDetail | null {
  if (detail == null || typeof detail !== "object") return null;
  const record = detail as Record<string, unknown>;
  // Bazı gövdeler {detail: {...}} olarak sarmalanır.
  const inner =
    "code" in record ? record : typeof record.detail === "object" && record.detail !== null ? (record.detail as Record<string, unknown>) : null;
  if (!inner || typeof inner.code !== "string" || typeof inner.message !== "string") {
    return null;
  }
  const conflicts = Array.isArray(inner.conflicts)
    ? inner.conflicts.filter((c): c is string => typeof c === "string")
    : [];
  return { code: inner.code, message: inner.message, conflicts };
}

/** Policy conflict kodunu Türkçe mesaja çevirir. */
export function policyConflictMessage(code: string): string {
  switch (code) {
    case "POLICY_NOT_CONFIGURABLE":
      return "Takip politikası bu aşamada yapılandırılamaz (doğrulama geçmiş ve taraf onayı bekleniyor olmalı).";
    case "POLICY_LOCKED":
      return "Takip politikası zaten kilitli; değiştirilemez.";
    case "POLICY_INVALID":
      return "Seçilen takip modu geçersiz.";
    case "POLICY_CONTRACT_CONFLICT":
      return "Sözleşme kanıt şartı bu takip modunu zorunlu kılıyor; daha zayıf bir mod seçilemez (sözleşmesel video ⇒ belge ve video).";
    default:
      return "Takip politikası işlemi tamamlanamadı. Durumu yenileyip tekrar deneyin.";
  }
}

/** Bir 409 policy hatasından en iyi mesajı üretir (envelope kodu, parse edilen detay, ya da genel). */
export function policyErrorMessage(code: string, detail: unknown): string {
  const parsed = parsePolicyConflict(detail);
  if (parsed) return policyConflictMessage(parsed.code);
  if (code && code !== "HTTP_409" && code !== "REQUEST_FAILED") {
    return policyConflictMessage(code);
  }
  return "Takip politikası işlemi tamamlanamadı (çakışma). Durumu yenileyip tekrar deneyin.";
}

/** Sistem öneri gerekçe kodlarını Türkçe etikete çevirir. */
export function reasonCodeLabel(code: string): string {
  switch (code) {
    case "PHYSICAL_GOODS":
      return "Fiziksel mal teslimi";
    case "PHYSICAL_UNIT":
      return "Fiziksel birim (adet/koli)";
    case "CONTRACTUAL_E_IRSALIYE":
      return "Sözleşmede e-irsaliye şartı";
    case "DELIVERY_TERMS":
      return "Teslimat koşulları";
    case "SERVICE_ONLY":
      return "Yalnız hizmet (fiziksel teslim yok)";
    case "CONFLICTING_SIGNALS":
      return "Çelişen sinyaller";
    case "INSUFFICIENT_SIGNAL":
      return "Yetersiz sinyal";
    default:
      return code;
  }
}

export function recommendationLabel(recommendation: string | null): string {
  switch (recommendation) {
    case "yes":
      return "Fiziksel teslimat takibi öneriliyor";
    case "no":
      return "Fiziksel teslimat takibi önerilmiyor";
    case "uncertain":
      return "Öneri belirsiz";
    default:
      return "Öneri yok";
  }
}

export const TRACKING_MODE_LABEL: Record<string, string> = {
  off: "Kapalı",
  document_only: "Yalnız belge",
  document_and_video: "Belge ve video",
};
