export interface ApiErrorEnvelope {
  code: string;
  message: string;
  request_id: string | null;
  detail?: Record<string, unknown>;
}

export type ApiErrorKind =
  | "session_required"
  | "permission_denied"
  | "conflict"
  | "validation"
  | "not_found"
  | "server"
  | "network"
  | "invalid_response"
  | "unknown";

export interface UserPublic {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  status: "active" | "disabled";
  platform_role: "reviewer" | "admin" | null;
  email_verified_at: string | null;
  created_at: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export type EntityType = "individual" | "company";
export type TaxIdentifierType = "tckn" | "vkn";
export type MembershipRole = "owner" | "admin" | "member";
export type VerificationStatus = "self_declared" | "pending" | "verified";

export interface EntityPublic {
  id: string;
  entity_type: EntityType;
  legal_name: string;
  tax_identifier_type: TaxIdentifierType;
  tax_identifier_last4: string;
  tax_office: string | null;
  address_json: Record<string, unknown> | null;
  verification_status: VerificationStatus;
  my_role: MembershipRole;
  created_at: string;
  updated_at: string;
}

export interface EntityCreateRequest {
  entity_type: EntityType;
  legal_name: string;
  tax_identifier_type: TaxIdentifierType;
  tax_identifier: string;
  tax_office: string | null;
  address_json: Record<string, unknown> | null;
}

export interface EntityUpdateRequest {
  legal_name?: string;
  tax_office?: string | null;
  address_json?: Record<string, unknown> | null;
}
