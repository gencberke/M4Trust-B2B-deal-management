import type { RedactedExtraction } from "../../../types/transactions";
import type {
  ExtractionCurrency,
  ExtractionEvidence,
  ExtractionRevisionInput,
  ExtractionTrigger,
} from "../../../types/rules";

// Form state, redacted extraction'ı yansıtır. source_quote form'da HİÇ yoktur —
// redacted okumalar quote taşımaz; revizyon gövdesinde her zaman OMİT edilir
// (null), backend değişmeyen kuralın alıntısını parent'tan birleştirir.
export interface RuleFormRow {
  milestone: string;
  trigger: string;
  percentage: string;
  required_evidence: string; // virgülle ayrılmış
  confidence: string;
}

export interface GoodsFormRow {
  name: string;
  quantity: string;
  unit: string;
}

export interface RevisionFormState {
  contract_id: string;
  buyer_name: string;
  seller_name: string;
  currency: string;
  total_amount: string;
  delivery_deadline: string;
  goods: GoodsFormRow[];
  payment_rules: RuleFormRow[];
  risk_flags: string; // virgülle ayrılmış
  needs_manual_review: boolean;
}

const CURRENCIES: ExtractionCurrency[] = ["TRY", "USD", "EUR", "OTHER"];
const TRIGGERS: ExtractionTrigger[] = ["approval", "e_invoice", "delivery_video", "manual_review"];
const EVIDENCE: ExtractionEvidence[] = ["contract", "e_irsaliye", "video"];

/** Redacted extraction'dan düzenlenebilir form state türetir. */
export function formStateFromExtraction(extraction: RedactedExtraction): RevisionFormState {
  return {
    contract_id: extraction.contract_id,
    buyer_name: extraction.parties.buyer?.name ?? "",
    seller_name: extraction.parties.seller?.name ?? "",
    currency: extraction.commercial_terms.currency,
    total_amount: String(extraction.commercial_terms.total_amount ?? ""),
    delivery_deadline: extraction.commercial_terms.delivery_deadline ?? "",
    goods: extraction.commercial_terms.goods.map((g) => ({
      name: g.name,
      quantity: String(g.quantity ?? ""),
      unit: g.unit,
    })),
    payment_rules: extraction.payment_rules.map((r) => ({
      milestone: r.milestone,
      trigger: r.trigger,
      percentage: String(r.percentage ?? ""),
      required_evidence: (r.required_evidence ?? []).join(", "),
      confidence: String(r.confidence ?? ""),
    })),
    risk_flags: (extraction.risk_flags ?? []).join(", "),
    needs_manual_review: extraction.needs_manual_review,
  };
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export interface BuildResult {
  ok: boolean;
  payload?: ExtractionRevisionInput;
  error?: string;
}

/**
 * Form state'inden revizyon gövdesi kurar. Sayısal alanları coerce eder ve
 * §4.2 tiplerini yansıtan minimal ön-doğrulama yapar (backend nihai otoritedir).
 * source_quote HER ZAMAN omit edilir (null) — asla boş/maskeli/kopyalanmış metin.
 */
export function buildRevisionPayload(state: RevisionFormState): BuildResult {
  if (!CURRENCIES.includes(state.currency as ExtractionCurrency)) {
    return { ok: false, error: "Geçersiz para birimi." };
  }
  const total = Number(state.total_amount);
  if (Number.isNaN(total)) {
    return { ok: false, error: "Toplam tutar sayısal olmalı." };
  }
  const deadline = state.delivery_deadline.trim();
  if (deadline && !/^\d{4}-\d{2}-\d{2}$/.test(deadline)) {
    return { ok: false, error: "Teslim tarihi YYYY-AA-GG biçiminde olmalı." };
  }

  const goods = [];
  for (const g of state.goods) {
    const quantity = Number(g.quantity);
    if (Number.isNaN(quantity)) return { ok: false, error: "Mal miktarı sayısal olmalı." };
    goods.push({ name: g.name.trim(), quantity, unit: g.unit.trim() });
  }

  const payment_rules = [];
  for (const r of state.payment_rules) {
    if (!TRIGGERS.includes(r.trigger as ExtractionTrigger)) {
      return { ok: false, error: `Geçersiz tetikleyici: ${r.trigger}` };
    }
    const percentage = Number(r.percentage);
    const confidence = Number(r.confidence);
    if (Number.isNaN(percentage) || Number.isNaN(confidence)) {
      return { ok: false, error: "Kural yüzde/güven değerleri sayısal olmalı." };
    }
    const evidence = splitList(r.required_evidence);
    for (const e of evidence) {
      if (!EVIDENCE.includes(e as ExtractionEvidence)) {
        return { ok: false, error: `Geçersiz kanıt türü: ${e}` };
      }
    }
    payment_rules.push({
      milestone: r.milestone.trim(),
      trigger: r.trigger as ExtractionTrigger,
      percentage,
      required_evidence: evidence as ExtractionEvidence[],
      // Redacted okumada alıntı yoktur → daima omit; backend parent'tan birleştirir.
      source_quote: null,
      confidence,
    });
  }

  return {
    ok: true,
    payload: {
      contract_id: state.contract_id.trim(),
      parties: {
        buyer: { name: state.buyer_name.trim(), tax_id: null },
        seller: { name: state.seller_name.trim(), tax_id: null },
      },
      commercial_terms: {
        currency: state.currency as ExtractionCurrency,
        total_amount: total,
        goods,
        delivery_deadline: deadline || null,
      },
      payment_rules,
      risk_flags: splitList(state.risk_flags),
      needs_manual_review: state.needs_manual_review,
    },
  };
}

/** Revizyon 409/422 kodlarını Türkçe mesaja çevirir (C3). */
export function revisionErrorMessage(code: string): string {
  switch (code) {
    case "STALE_RULE_SET_VERSION":
      return "Kural sürümü artık güncel değil; sürümleri yenileyip tekrar deneyin.";
    case "RULE_REVISION_AFTER_RATIFICATION":
      return "Onay sonrası kurallar değiştirilemez.";
    case "RULE_REVISION_NOT_ALLOWED":
      return "Bu işlem durumunda kural revizyonu yapılamaz.";
    case "LEGACY_RULE_REVISION_FORBIDDEN":
      return "Legacy işlemlerde kural revizyonu yapılamaz.";
    case "RULE_REVISION_FORBIDDEN":
      return "Kural revizyonu yalnız işlemi oluşturan yönetici tarafından yapılabilir.";
    case "RULE_REVISION_CONFLICT":
      return "Eşzamanlı bir değişiklik nedeniyle revizyon oluşturulamadı; yenileyip tekrar deneyin.";
    case "RULE_REVISION_SOURCE_QUOTE_REQUIRED":
      return "Yeni bir kural için sözleşme alıntısı gereklidir; bu alan redakte okumadan gelmediğinden yeni kural bu ekrandan eklenemez.";
    case "PACKAGE_INTEGRITY_FAILED":
      return "Paket bütünlüğü doğrulanamadı.";
    case "PACKAGE_INPUTS_INVALID":
      return "Paket girdileri geçersiz.";
    case "RULE_SET_NOT_FOUND":
    case "TRANSACTION_NOT_FOUND":
      return "Kayıt bulunamadı; sürümleri yenileyin.";
    default:
      return "Kural işlemi tamamlanamadı. Verileri yenileyip tekrar deneyin.";
  }
}
