export type TrackingMode = "off" | "document_only" | "document_and_video";
export type PhysicalDeliveryRecommendation = "yes" | "no" | "uncertain" | (string & {});
export type TrackingPolicyStatus = "draft" | "locked" | (string & {});

export interface TrackingPolicySnapshot {
  transaction_id: string;
  recommendation: PhysicalDeliveryRecommendation | null;
  recommendation_reason_codes: string[];
  manager_physical_delivery_confirmed: boolean | null;
  tracking_mode: TrackingMode | (string & {});
  video_role: "advisory" | (string & {});
  status: TrackingPolicyStatus;
  configured_at: string | null;
  locked_at: string | null;
}

// GET /api/transactions/{id}/tracking-policy
export interface TrackingPolicyView {
  tracking_policy: TrackingPolicySnapshot;
  ready_for_policy: boolean;
  contractual_required_evidence: string[];
}

// PUT / lock responses
export interface TrackingPolicyUpdateResult {
  updated: boolean;
  tracking_policy: TrackingPolicySnapshot;
}
export interface TrackingPolicyLockResult {
  locked: boolean;
  tracking_policy: TrackingPolicySnapshot;
}

export interface TrackingPolicyUpdateInput {
  physical_delivery_confirmed: boolean;
  tracking_mode: TrackingMode;
}

// 409 detail (best-effort; genelde client tarafından yakalanamaz — bkz. policyLogic).
export interface PolicyConflictDetail {
  code: string;
  message: string;
  conflicts: string[];
}
