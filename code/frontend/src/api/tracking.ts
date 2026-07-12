import { apiRequest } from "./client";
import type {
  TrackingPolicyLockResult,
  TrackingPolicyUpdateInput,
  TrackingPolicyUpdateResult,
  TrackingPolicyView,
} from "../types/tracking";

// 404 (henüz policy yok) inline ele alınır → yönlendirme kapalı.
export function getTrackingPolicy(transactionId: string): Promise<TrackingPolicyView> {
  return apiRequest<TrackingPolicyView>(
    `/transactions/${encodeURIComponent(transactionId)}/tracking-policy`,
    { redirectOnError: false },
  );
}

export function updateTrackingPolicy(
  transactionId: string,
  body: TrackingPolicyUpdateInput,
): Promise<TrackingPolicyUpdateResult> {
  return apiRequest<TrackingPolicyUpdateResult>(
    `/transactions/${encodeURIComponent(transactionId)}/tracking-policy`,
    { method: "PUT", body, csrf: true, redirectOnError: false },
  );
}

export function lockTrackingPolicy(transactionId: string): Promise<TrackingPolicyLockResult> {
  // Account_v2: boş gövde; yetkilendirme session + acting-entity'den gelir.
  return apiRequest<TrackingPolicyLockResult>(
    `/transactions/${encodeURIComponent(transactionId)}/tracking-policy/lock`,
    { method: "POST", body: {}, csrf: true, redirectOnError: false },
  );
}
