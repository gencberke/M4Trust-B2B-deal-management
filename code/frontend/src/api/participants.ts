import { apiRequest } from "./client";
import type {
  Participant,
  ParticipantPublicView,
  ProfileUpdateRequest,
} from "../types/participants";

export function listParticipants(transactionId: string): Promise<ParticipantPublicView[]> {
  return apiRequest<ParticipantPublicView[]>(
    `/transactions/${encodeURIComponent(transactionId)}/participants`,
  );
}

export function updateMyProfile(
  transactionId: string,
  body: ProfileUpdateRequest,
): Promise<Participant> {
  return apiRequest<Participant>(
    `/transactions/${encodeURIComponent(transactionId)}/participants/me/profile`,
    { method: "PUT", body, csrf: true, redirectOnError: false },
  );
}

export function confirmMyProfile(transactionId: string): Promise<Participant> {
  return apiRequest<Participant>(
    `/transactions/${encodeURIComponent(transactionId)}/participants/me/confirm`,
    { method: "POST", csrf: true, redirectOnError: false },
  );
}
