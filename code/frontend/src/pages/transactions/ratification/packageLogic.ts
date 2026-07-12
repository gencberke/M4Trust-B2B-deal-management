import type { ApiClientError } from "../../../api/client";
import type {
  CanonicalPackagePayload,
  FundingScheduleSpecInput,
  MilestoneReleaseOverride,
} from "../../../types/ratification";

/** Current package 404 = "henüz paket yok" normal ön-durumu (hata değil). */
export function isNoPackageError(error: ApiClientError): boolean {
  return error.status === 404;
}

/** Paket build readiness 409 kodlarını Türkçe checklist satırına çevirir. */
export function readinessChecklist(code: string): string {
  switch (code) {
    case "DOCUMENT_NOT_READY":
      return "Sözleşme belgesi hazır değil.";
    case "RULE_SET_NOT_READY":
      return "Kural seti hazır değil (extraction/doğrulama tamamlanmadı).";
    case "RULE_SET_NOT_RATIFIABLE":
      return "Kural seti onaya uygun değil (doğrulama geçmedi).";
    case "PARTICIPANTS_NOT_CONFIRMED":
      return "Taraf profilleri onaylanmadı.";
    case "PARTICIPANTS_NOT_BOUND":
      return "Taraflar henüz bağlanmadı (davet kabul edilmedi).";
    case "SAME_LEGAL_ENTITY":
      return "Alıcı ve satıcı aynı tüzel kişi olamaz.";
    case "TRACKING_POLICY_NOT_LOCKED":
      return "Takip politikası kilitlenmedi.";
    case "BLOCKING_REVIEW":
      return "Engelleyici bir inceleme açık.";
    case "PACKAGE_INPUTS_CHANGED":
      return "Paket girdileri değişti; paket yeniden oluşturulacak.";
    case "PACKAGE_INTEGRITY_FAILED":
      return "Paket bütünlüğü doğrulanamadı.";
    case "PROVIDER_CAPABILITY_CONFLICT":
      return "Ödeme sağlayıcısı bu fonlama planını desteklemiyor.";
    case "MOKA_REQUIRES_FIXED_FUNDING_UNITS":
      return "Moka profili sabit fonlama birimleri gerektiriyor.";
    default:
      return `Hazır değil: ${code}`;
  }
}

/** Ratify 409/403 kodlarını Türkçe mesaja çevirir (C7). */
export function ratifyErrorMessage(code: string): string {
  switch (code) {
    case "RATIFICATION_NOT_AUTHORIZED":
      return "Onaylama yetkiniz yok (paketin tarafı değilsiniz veya aynı kullanıcı her iki tarafı temsil edemez).";
    case "PACKAGE_NOT_OPEN":
      return "Paket onaya açık değil.";
    case "PACKAGE_SUPERSEDED":
      return "Paket girdiler değiştiği için yenilendi; güncel paketi inceleyip yeniden onaylayın.";
    case "PACKAGE_CANCELLED":
      return "Paket iptal edilmiş.";
    case "PACKAGE_ALREADY_COMPLETE":
      return "Paket zaten tamamlanmış.";
    case "PACKAGE_INTEGRITY_FAILED":
      return "Paket bütünlüğü doğrulanamadı.";
    case "FUNDING_COORDINATOR_CONFLICT":
      return "Fonlama başlatılırken çakışma oluştu; durumu yenileyin.";
    case "PACKAGE_NOT_FOUND":
      return "Paket bulunamadı.";
    default:
      return "Onay tamamlanamadı. Durumu yenileyip tekrar deneyin.";
  }
}

export const RATIFY_NETWORK_WARNING =
  "İstek sunucuya ulaşmadan kesilmiş olabilir. Tekrar denemeden önce paket durumunu yenileyin — " +
  "onay kaydınız oluşmuş olabilir (tekrar onay güvenli biçimde yok sayılır).";

// --- Funding schedule flattening (SALT gösterim; hiçbir toplama/hash yok) -----

export interface ScheduleUnitRow {
  sequence: number;
  amount_minor: number;
  eligibility_type: string;
}

export interface ScheduleMilestoneRow {
  rule_index: number;
  title: string;
  trigger_type: string;
  basis_points: number;
  amount_minor: number;
  currency: string;
  required_evidence: string[];
  release_mode: string;
  units: ScheduleUnitRow[];
}

/** Canonical payload'daki funding_schedule'ı düz satırlara çevirir (yalnız yeniden şekillendirme). */
export function scheduleRows(payload: CanonicalPackagePayload): ScheduleMilestoneRow[] {
  const schedule = payload.funding_schedule;
  if (!schedule) return [];
  return schedule.milestones.map((m) => ({
    rule_index: m.rule_index,
    title: m.title,
    trigger_type: m.trigger_type,
    basis_points: m.basis_points,
    amount_minor: m.amount_minor,
    currency: m.currency,
    required_evidence: m.required_evidence,
    release_mode: m.release_mode,
    units: m.funding_units.map((u) => ({
      sequence: u.sequence,
      amount_minor: u.amount_minor,
      eligibility_type: u.eligibility_type,
    })),
  }));
}

export interface BuildSpecFormRow {
  rule_index: number;
  release_mode: "all_or_nothing" | "fixed_tranches";
  tranche_count: string;
}

export type BuildSpecResult =
  | { ok: true; spec: FundingScheduleSpecInput }
  | { ok: false; error: string };

/**
 * Form satırlarından build spec'i kurar. fixed_tranches için tranche_count ≥2
 * doğrular. Varsayılan (override yok) tüm milestone'ları all_or_nothing yapar.
 */
export function buildSpecFromForm(rows: BuildSpecFormRow[]): BuildSpecResult {
  const overrides: MilestoneReleaseOverride[] = [];
  for (const row of rows) {
    if (row.release_mode === "all_or_nothing") {
      overrides.push({ rule_index: row.rule_index, release_mode: "all_or_nothing" });
      continue;
    }
    const count = Number(row.tranche_count);
    if (!Number.isInteger(count) || count < 2) {
      return { ok: false, error: "Sabit dilim için dilim sayısı en az 2 olmalı." };
    }
    overrides.push({
      rule_index: row.rule_index,
      release_mode: "fixed_tranches",
      tranche_count: count,
    });
  }
  return { ok: true, spec: { overrides } };
}
