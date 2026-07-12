export type ParticipantRole = "buyer" | "seller";

export type ParticipantStatus =
  | "invited"
  | "profile_incomplete"
  | "ready"
  | "confirmed"
  | (string & {});

export interface PartyProfileSnapshot {
  name: string;
  tax_id?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  address?: string | null;
}

// Kendi tarafın tam görünümü (own-party mutation cevapları).
export interface Participant {
  id: string;
  transaction_id: string;
  role: ParticipantRole;
  legal_entity_id: string | null;
  status: ParticipantStatus;
  extracted_snapshot: PartyProfileSnapshot | null;
  declared_snapshot: PartyProfileSnapshot | null;
  confirmed_snapshot: PartyProfileSnapshot | null;
  confirmed_at: string | null;
  created_at: string;
  updated_at: string;
}

// Public liste — PII taşımaz (e-posta/tax/telefon yok).
export interface ParticipantPublicView {
  id: string;
  role: ParticipantRole;
  status: ParticipantStatus;
  display_name: string | null;
  confirmed: boolean;
  confirmed_at: string | null;
}

export interface InvitationCreateRequest {
  participant_role: ParticipantRole;
  invited_email: string;
}

export interface InvitationCreateResult {
  invitation_id: string;
  participant_role: ParticipantRole;
  expires_at: string;
  invite_link: string;
}

export interface InvitationPreview {
  participant_role: ParticipantRole;
  transaction_reference: string;
}

export interface InvitationAcceptRequest {
  legal_entity_id: string;
}

export interface ProfileUpdateRequest {
  snapshot: PartyProfileSnapshot;
}
