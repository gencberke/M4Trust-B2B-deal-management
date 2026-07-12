// Backend alan adları birebir (snake_case) kullanılır — adapter katmanı yok.
// Redacted projeksiyon: tax_id ve source_quote HİÇBİR yerde yok (master §6/§9.6).

export type LifecycleVersion = "legacy_v1" | "account_v2";

export type AccountState =
  | "preparation"
  | "uploaded"
  | "extracting"
  | "awaiting_review"
  | "awaiting_approval"
  | "awaiting_ratification"
  | "funding_pending"
  | "active"
  | "settled"
  | "rejected"
  | "cancelled"
  | (string & {});

export interface TransactionListItem {
  id: string;
  state: AccountState;
  created_at: string;
  buyer_name: string | null;
  seller_name: string | null;
}

export interface ExtractionPartyView {
  name: string;
}

export interface ExtractionGoods {
  name: string;
  quantity: number;
  unit: string;
}

export interface ExtractionPaymentRule {
  milestone: string;
  trigger: string;
  percentage: number;
  required_evidence: string[];
  confidence: number;
}

export interface RedactedExtraction {
  contract_id: string;
  parties: { buyer: ExtractionPartyView; seller: ExtractionPartyView };
  commercial_terms: {
    currency: string;
    total_amount: number;
    goods: ExtractionGoods[];
    delivery_deadline: string | null;
  };
  payment_rules: ExtractionPaymentRule[];
  risk_flags: string[];
  needs_manual_review: boolean;
}

export interface ValidatorFinding {
  code: string;
  severity: string;
  message?: string;
}

export interface ValidatorReport {
  status: "PASS" | "NEEDS_REVIEW" | "REJECT" | (string & {}) | null;
  findings: ValidatorFinding[] | null;
}

export interface TransactionEvent {
  id: number;
  event_type: string;
  payload: Record<string, unknown> | null;
  source: string;
  created_at: string;
}

export interface LegacyPaymentRow {
  other_trx_code: string;
  virtual_pos_order_id: string | null;
  status: string;
  amount: number;
  created_at: string;
}

export interface TransactionDetail {
  id: string;
  state: AccountState;
  created_at: string;
  lifecycle_version: LifecycleVersion;
  canonical_state: string | null;
  extraction: RedactedExtraction | null;
  validator: ValidatorReport | null;
  events: TransactionEvent[];
  payment: LegacyPaymentRow[] | null;
}

export interface CreatedInvitationView {
  invitation_id: string;
  participant_role: string;
  expires_at: string;
  invite_link: string;
  notification_delivered?: boolean;
}

export interface CreateTransactionResponse {
  id: string;
  lifecycle_version: "account_v2";
  own_role: "buyer" | "seller";
  acting_entity_id: string;
  invitation: CreatedInvitationView | null;
}

export interface ExtractionRetryResponse {
  transaction_id: string;
  job_id: string;
  job_status: string | null;
  attempt_count: number | null;
  transaction_state: string | null;
}
