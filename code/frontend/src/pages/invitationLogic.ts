/** Davet önizlemesi 404 (bilinmeyen/kabul/iptal/expired) için tek generic metin. */
export function previewUnavailableMessage(): string {
  return "Davet geçersiz, süresi dolmuş veya iptal edilmiş olabilir.";
}

/**
 * Accept hata kodlarını Türkçe mesaja çevirir (C7). Zarf kodu yoksa
 * status'a göre düşülür; hepsinde generic fallback vardır.
 */
export function acceptErrorMessage(code: string, status: number | null): string {
  switch (code) {
    case "INVITATION_EMAIL_MISMATCH":
      return "Bu davet başka bir e-posta adresine gönderilmiş.";
    case "INVITATION_NOT_ACCEPTABLE":
      return "Bu davet daha önce kullanılmış veya artık geçerli değil.";
    case "PARTICIPANT_CONFLICT":
      return "Bu rol zaten bağlanmış veya entity çakışması var.";
    case "INVITATION_FORBIDDEN":
      return "Bu daveti kabul etme yetkiniz yok (uygun bir üyeliğiniz olmayabilir).";
    case "INVITATION_NOT_FOUND":
      return "Davet bulunamadı.";
    default:
      break;
  }
  switch (status) {
    case 403:
      return "Bu daveti kabul etme yetkiniz yok.";
    case 404:
      return "Davet bulunamadı.";
    case 409:
      return "Bu davet daha önce kullanılmış veya artık geçerli değil.";
    default:
      return "Davet kabul edilemedi. Lütfen tekrar deneyin.";
  }
}
