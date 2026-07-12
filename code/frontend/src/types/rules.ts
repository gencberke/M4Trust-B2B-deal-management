import type { RedactedExtraction } from "./transactions";

export type RuleSetStatus =
  | "draft"
  | "validated"
  | "ratifiable"
  | "superseded"
  | "ratified"
  | (string & {});

// GET /rule-sets versions[] öğesi ve revision/validate cevabı (redacted, no source_quote).
export interface RuleSetVersionPublicView {
  id: string;
  transaction_id: string;
  version: number;
  parent_version_id: string | null;
  extraction: RedactedExtraction;
  rules_hash: string;
  validator_status: string | null;
  validator_report: { code: string; severity: string }[] | null;
  status: RuleSetStatus;
  created_by_user_id: string | null;
  created_at: string;
}

// GET /api/transactions/{id}/rule-sets
export interface RuleSetVersionHistory {
  transaction_id: string;
  current_version_id: string | null;
  current_version: RuleSetVersionPublicView | null;
  versions: RuleSetVersionPublicView[];
}

// Revision request — full §4.2 shape, but source_quote is OMITTABLE (null → merged
// from parent at same rule index by the backend). Never send "" or masked text.
export type ExtractionCurrency = "TRY" | "USD" | "EUR" | "OTHER";
export type ExtractionTrigger = "approval" | "e_invoice" | "delivery_video" | "manual_review";
export type ExtractionEvidence = "contract" | "e_irsaliye" | "video";

export interface ExtractionRevisionPaymentRule {
  milestone: string;
  trigger: ExtractionTrigger;
  percentage: number;
  required_evidence: ExtractionEvidence[];
  source_quote?: string | null;
  confidence: number;
}

export interface ExtractionRevisionInput {
  contract_id: string;
  parties: { buyer: { name: string; tax_id: string | null }; seller: { name: string; tax_id: string | null } };
  commercial_terms: {
    currency: ExtractionCurrency;
    total_amount: number;
    goods: { name: string; quantity: number; unit: string }[];
    delivery_deadline: string | null;
  };
  payment_rules: ExtractionRevisionPaymentRule[];
  risk_flags: string[];
  needs_manual_review: boolean;
}
