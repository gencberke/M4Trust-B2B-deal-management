import type { StatusDescriptor, StatusMap } from "./statusMaps";
import type { AccountState, RedactedExtraction } from "../types/transactions";

export const LIFECYCLE_STEPS = ["Yükleme", "Taraflar", "Politika", "Onay", "Fonlama", "Teslimat", "Kapanış"] as const;
export type LifecycleRole = "buyer" | "seller" | "manager" | "reviewer" | "unknown";
export type LifecycleSection = "overview" | "parties" | "rules" | "ratification" | "fulfillment" | "payments";
export type LifecycleNavBadge = "action" | "waiting" | "done";
export interface LifecycleNextAction { label: string; targetSection: LifecycleSection; role: LifecycleRole | "counterparty" | "system" | "none"; blockedReason?: string; }
export interface LifecycleDescriptor extends StatusDescriptor { stepIndex: number; stepLabel: (typeof LIFECYCLE_STEPS)[number]; description: string; nextAction: LifecycleNextAction; terminal?: boolean; }

function state(stepIndex: number, label: string, tone: StatusDescriptor["tone"], description: string, actionLabel: string, targetSection: LifecycleSection, role: LifecycleNextAction["role"], blockedReason?: string): LifecycleDescriptor {
  return { stepIndex, stepLabel: LIFECYCLE_STEPS[stepIndex], label, tone, description, nextAction: { label: actionLabel, targetSection, role, blockedReason } };
}

const STATES: Record<string, LifecycleDescriptor> = {
  preparation: state(0, "Hazırlık", "info", "Sözleşme yükleme ve ilk hazırlık sürüyor.", "Sözleşme özetini kontrol et", "overview", "system"),
  uploaded: state(0, "İşleniyor", "info", "Sözleşme güvenli işleme kuyruğuna alındı.", "Çıkarımın tamamlanmasını bekle", "overview", "system"),
  extracting: state(0, "İşleniyor", "info", "Sözleşme kuralları çıkarılıyor.", "Çıkarım durumunu izle", "overview", "system"),
  awaiting_review: state(2, "Manuel inceleme", "warning", "Engelleyici bulgular çözülmeden onay paketi oluşturulamaz.", "İnceleme bulgularını çöz", "rules", "reviewer"),
  awaiting_approval: state(2, "Onay hazırlığı", "info", "Taraflar ve politika onay paketine hazırlanıyor.", "Politikayı kilitle ve paketi hazırla", "ratification", "manager"),
  awaiting_ratification: state(3, "Taraf onayı", "info", "Canonical paket iki tarafın onayını bekliyor.", "Paketi onayla", "ratification", "buyer"),
  funding_pending: state(4, "Fonlama bekliyor", "warning", "Havuz fonlaması güvenli biçimde hazırlanıyor.", "Fonlama durumunu izle", "payments", "system"),
  active: state(5, "Aktif", "success", "İşlem aktif; teslimat kanıtları sunulabilir.", "Teslimat kanıtı ekle", "fulfillment", "seller"),
  settled: { ...state(6, "Tamamlandı", "success", "İşlem ve ödeme yaşam döngüsü tamamlandı.", "İşlem kaydını incele", "overview", "none"), terminal: true },
  rejected: { ...state(0, "Reddedildi", "danger", "Doğrulama bulguları nedeniyle işlem durduruldu.", "Doğrulama bulgularını incele", "rules", "none", "İşlem reddedildi."), terminal: true },
  cancelled: { ...state(0, "İptal", "neutral", "İşlem iptal edildi.", "İşlem kaydını incele", "overview", "none", "İşlem iptal edildi."), terminal: true },
};
const UNKNOWN = state(0, "Bilinmeyen durum", "neutral", "İşlem durumu görüntüleniyor.", "Genel bakışı incele", "overview", "none");

export const transactionStateMap: StatusMap = Object.fromEntries(Object.entries(STATES).map(([key, value]) => [key, { label: value.label, tone: value.tone }]));

export function lifecycleFor(stateValue: AccountState, role: LifecycleRole = "unknown"): LifecycleDescriptor {
  const descriptor = STATES[stateValue] ?? { ...UNKNOWN, label: stateValue || UNKNOWN.label };
  const action = descriptor.nextAction;
  if (action.role === "none" || action.role === "system" || action.role === role) return descriptor;
  if (stateValue === "awaiting_review" && role !== "reviewer") return waiting(descriptor, "Platform incelemesi bekleniyor.");
  if (stateValue === "awaiting_ratification" && role === "seller") return { ...descriptor, nextAction: { ...action, role: "seller" } };
  if (stateValue === "active" && role === "manager") return { ...descriptor, nextAction: { ...action, role: "manager" } };
  return waiting(descriptor, action.role === "manager" ? "İşlem yöneticisinin aksiyonu bekleniyor." : "Karşı tarafın aksiyonu bekleniyor.");
}

function waiting(descriptor: LifecycleDescriptor, reason: string): LifecycleDescriptor {
  return { ...descriptor, nextAction: { ...descriptor.nextAction, role: "counterparty", blockedReason: reason } };
}

export function inferLifecycleRole(entityName: string | null | undefined, extraction: RedactedExtraction | null): LifecycleRole {
  const normalized = entityName?.trim().toLocaleLowerCase("tr-TR");
  if (!normalized || !extraction) return "manager";
  if (extraction.parties.buyer.name?.trim().toLocaleLowerCase("tr-TR") === normalized) return "buyer";
  if (extraction.parties.seller.name?.trim().toLocaleLowerCase("tr-TR") === normalized) return "seller";
  return "manager";
}

const SECTION_STEP: Record<string, number> = { overview: 0, parties: 1, rules: 2, ratification: 3, payments: 4, fulfillment: 5, disputes: 5 };
export function lifecycleSectionState(section: string, lifecycle: LifecycleDescriptor): { badge?: LifecycleNavBadge; muted: boolean } {
  const step = SECTION_STEP[section];
  if (step === undefined) return { muted: true };
  if (section === lifecycle.nextAction.targetSection) return { badge: lifecycle.nextAction.role === "counterparty" ? "waiting" : "action", muted: false };
  if (step < lifecycle.stepIndex || lifecycle.terminal) return { badge: "done", muted: false };
  if (step > lifecycle.stepIndex) return { badge: "waiting", muted: true };
  return { muted: false };
}
