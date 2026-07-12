/**
 * Event tipi → Türkçe etiket. ARCHITECTURE §4.3 event tipleri + Plan 06
 * funding-unit event'leri. Bilinmeyen tip için `eventLabel` ham tipi döndürür
 * (crash yerine izlenebilir görüntü).
 */
export const eventLabels: Record<string, string> = {
  contract_extracted: "Sözleşme çözümlendi",
  rules_validated: "Kurallar doğrulandı",
  rule_set_revised: "Kural seti güncellendi",
  tracking_policy_recommended: "Takip politikası önerildi",
  tracking_policy_updated: "Takip politikası güncellendi",
  tracking_policy_locked: "Takip politikası kilitlendi",
  buyer_approved: "Alıcı onayladı",
  seller_approved: "Satıcı onayladı",
  e_irsaliye_received: "E-irsaliye alındı",
  delivery_video_analyzed: "Teslimat videosu analiz edildi",
  evidence_submitted: "Teslimat kanıtı gönderildi",
  payment_decision_created: "Ödeme kararı oluşturuldu",
  mock_payment_executed: "Ödeme işlendi (simülasyon)",
  dispute_opened: "Uyuşmazlık açıldı",
  dispute_action_recorded: "Uyuşmazlık aksiyonu kaydedildi",
  funding_required: "Fonlama gerekli",
  funding_units_pool_created: "Fonlama birimleri oluşturuldu",
  funding_units_approved: "Fonlama birimleri onaylandı",
  transaction_settled: "İşlem tamamlandı",
};

export function eventLabel(eventType: string): string {
  return eventLabels[eventType] ?? eventType;
}
