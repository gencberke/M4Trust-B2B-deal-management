import { apiRequest } from "./client";
import type {
  InvitationAcceptRequest,
  InvitationCreateRequest,
  InvitationCreateResult,
  InvitationPreview,
  Participant,
} from "../types/participants";

export function createInvitation(
  transactionId: string,
  body: InvitationCreateRequest,
): Promise<InvitationCreateResult> {
  return apiRequest<InvitationCreateResult>(
    `/transactions/${encodeURIComponent(transactionId)}/invitations`,
    { method: "POST", body, csrf: true, redirectOnError: false },
  );
}

// Auth'suz önizleme; 404 satır içi gösterilir (yönlendirme kapalı).
export function previewInvitation(token: string): Promise<InvitationPreview> {
  return apiRequest<InvitationPreview>(
    `/invitations/${encodeURIComponent(token)}/preview`,
    { redirectOnError: false },
  );
}

export function acceptInvitation(
  token: string,
  body: InvitationAcceptRequest,
): Promise<Participant> {
  return apiRequest<Participant>(`/invitations/${encodeURIComponent(token)}/accept`, {
    method: "POST",
    body,
    csrf: true,
    redirectOnError: false,
  });
}

export function revokeInvitation(
  transactionId: string,
  invitationId: string,
): Promise<{ status: string }> {
  return apiRequest<{ status: string }>(
    `/transactions/${encodeURIComponent(transactionId)}/invitations/${encodeURIComponent(invitationId)}/revoke`,
    { method: "POST", csrf: true, redirectOnError: false },
  );
}
