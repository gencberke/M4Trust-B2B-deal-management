export type RatificationPackageStatus =
  | "draft"
  | "open"
  | "complete"
  | "superseded"
  | "cancelled"
  | (string & {});

export interface FundingUnitSpec {
  sequence: number;
  amount_minor: number;
  eligibility_type: string;
  eligibility_payload: Record<string, unknown>;
}

export interface FundingScheduleMilestone {
  rule_index: number;
  title: string;
  trigger_type: string;
  basis_points: number;
  amount_minor: number;
  currency: string;
  required_evidence: string[];
  release_mode: "all_or_nothing" | "fixed_tranches" | (string & {});
  funding_units: FundingUnitSpec[];
}

export interface CanonicalPackagePayload {
  funding_schedule?: {
    currency: string;
    total_amount_minor: number;
    milestones: FundingScheduleMilestone[];
  };
  commercial_summary?: {
    currency: string;
    total_amount_minor: number;
    delivery_deadline: string | null;
    goods: { name: string; quantity: number; unit: string }[];
  };
  tracking_policy?: { snapshot?: Record<string, unknown> };
  rule_set?: { id: string; version: number; rules_hash: string };
  package_schema_version?: string;
  provider_profile?: string;
}

export interface RatificationProgress {
  ratified: boolean;
  approved_at: string | null;
}

export interface RatificationPackagePublicView {
  id: string;
  transaction_id: string;
  version: number;
  status: RatificationPackageStatus;
  package_hash: string;
  canonical_payload: CanonicalPackagePayload;
  created_at: string;
  opened_at: string | null;
  completed_at: string | null;
  ratifications: Partial<Record<"buyer" | "seller", RatificationProgress>>;
}

// Build request
export interface MilestoneReleaseOverride {
  rule_index: number;
  release_mode: "all_or_nothing" | "fixed_tranches";
  tranche_count?: number;
}
export interface FundingScheduleSpecInput {
  overrides: MilestoneReleaseOverride[];
}

export interface RatificationView {
  id: string;
  package_id: string;
  transaction_id: string;
  participant_id: string;
  user_id: string;
  legal_entity_id: string;
  participant_role: string;
  auth_method: string;
  approved_at: string;
}

export interface RatificationOutcome {
  ratification: RatificationView;
  package_status: RatificationPackageStatus;
  funding_triggered: boolean;
}
