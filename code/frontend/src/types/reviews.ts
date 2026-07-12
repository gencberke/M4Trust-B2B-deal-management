// Manual review domain types — backend field names verbatim (snake_case).
// Free text only in ReviewActionRequest.comment; case fields are deterministic/PII-free.

export type ReviewPhase = "pre_ratification" | "settlement" | "payment" | (string & {});
export type ReviewSourceType =
  | "validator"
  | "party_mismatch"
  | "evidence"
  | "video"
  | "payment"
  | "system"
  | (string & {});
export type ReviewSeverity = "warning" | "blocking" | (string & {});
export type ReviewStatus =
  | "open"
  | "evidence_requested"
  | "resolved"
  | "escalated"
  | "cancelled"
  | (string & {});
export type ReviewActionType =
  | "comment"
  | "request_evidence"
  | "resolve_continue"
  | "resolve_reject"
  | "escalate"
  | "escalate_dispute"
  | "cancel";

export interface ReviewCase {
  id: string;
  transaction_id: string;
  phase: ReviewPhase;
  source_type: ReviewSourceType;
  source_id: string | null;
  reason_code: string;
  title: string;
  description: string;
  severity: ReviewSeverity;
  status: ReviewStatus;
  assigned_to_user_id: string | null;
  opened_by_actor_type: string;
  opened_by_user_id: string | null;
  resolved_by_user_id: string | null;
  resolution_code: string | null;
  resolution_note: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface ReviewAction {
  id: string;
  review_case_id: string;
  actor_user_id: string;
  acting_entity_id: string | null;
  action: ReviewActionType;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface ReviewCaseWithActions {
  case: ReviewCase;
  actions: ReviewAction[];
}

export interface ReviewActionRequest {
  action: ReviewActionType;
  comment?: string;
  resolution_code?: string;
}
