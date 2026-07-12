import type { RedactedExtraction } from "../../../types/transactions";

export type DiffKind = "changed" | "added" | "removed";

export interface DiffRow {
  path: string;
  kind: DiffKind;
  before: string;
  after: string;
}

const NONE = "—";

function scalar(value: unknown): string {
  if (value === null || value === undefined) return NONE;
  if (Array.isArray(value)) return value.map((v) => String(v)).join(", ") || NONE;
  return String(value);
}

/**
 * İki redacted extraction'ın alan-alan yapısal farkı — SALT gösterim.
 * Anlamsal yorum yok; payment_rules index'e göre, goods index'e göre, skaler
 * alanlar path'e göre eşlenir. source_quote redacted okumalarda hiç yoktur.
 */
export function diffExtraction(
  a: RedactedExtraction | null,
  b: RedactedExtraction | null,
): DiffRow[] {
  if (!a || !b) return [];
  const rows: DiffRow[] = [];

  const push = (path: string, before: unknown, after: unknown) => {
    const bs = scalar(before);
    const as = scalar(after);
    if (bs !== as) rows.push({ path, kind: "changed", before: bs, after: as });
  };

  push("contract_id", a.contract_id, b.contract_id);
  push("parties.buyer.name", a.parties.buyer?.name, b.parties.buyer?.name);
  push("parties.seller.name", a.parties.seller?.name, b.parties.seller?.name);
  push("commercial_terms.currency", a.commercial_terms.currency, b.commercial_terms.currency);
  push("commercial_terms.total_amount", a.commercial_terms.total_amount, b.commercial_terms.total_amount);
  push("commercial_terms.delivery_deadline", a.commercial_terms.delivery_deadline, b.commercial_terms.delivery_deadline);
  push("risk_flags", a.risk_flags, b.risk_flags);
  push("needs_manual_review", a.needs_manual_review, b.needs_manual_review);

  const maxGoods = Math.max(a.commercial_terms.goods.length, b.commercial_terms.goods.length);
  for (let i = 0; i < maxGoods; i++) {
    const ga = a.commercial_terms.goods[i];
    const gb = b.commercial_terms.goods[i];
    if (ga && !gb) {
      rows.push({ path: `goods[${i}]`, kind: "removed", before: `${ga.name} (${ga.quantity} ${ga.unit})`, after: NONE });
    } else if (!ga && gb) {
      rows.push({ path: `goods[${i}]`, kind: "added", before: NONE, after: `${gb.name} (${gb.quantity} ${gb.unit})` });
    } else if (ga && gb) {
      push(`goods[${i}].name`, ga.name, gb.name);
      push(`goods[${i}].quantity`, ga.quantity, gb.quantity);
      push(`goods[${i}].unit`, ga.unit, gb.unit);
    }
  }

  const maxRules = Math.max(a.payment_rules.length, b.payment_rules.length);
  for (let i = 0; i < maxRules; i++) {
    const ra = a.payment_rules[i];
    const rb = b.payment_rules[i];
    if (ra && !rb) {
      rows.push({ path: `payment_rules[${i}]`, kind: "removed", before: `${ra.milestone} (%${ra.percentage})`, after: NONE });
    } else if (!ra && rb) {
      rows.push({ path: `payment_rules[${i}]`, kind: "added", before: NONE, after: `${rb.milestone} (%${rb.percentage})` });
    } else if (ra && rb) {
      push(`payment_rules[${i}].milestone`, ra.milestone, rb.milestone);
      push(`payment_rules[${i}].trigger`, ra.trigger, rb.trigger);
      push(`payment_rules[${i}].percentage`, ra.percentage, rb.percentage);
      push(`payment_rules[${i}].required_evidence`, ra.required_evidence, rb.required_evidence);
    }
  }

  return rows;
}
