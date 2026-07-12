import { apiRequest } from "./client";
import type {
  FundingScheduleSpecInput,
  RatificationOutcome,
  RatificationPackagePublicView,
} from "../types/ratification";

export function buildRatificationPackage(
  transactionId: string,
  body: { funding_schedule_spec?: FundingScheduleSpecInput },
): Promise<RatificationPackagePublicView> {
  return apiRequest<RatificationPackagePublicView>(
    `/transactions/${encodeURIComponent(transactionId)}/ratification-packages`,
    { method: "POST", body, csrf: true, redirectOnError: false },
  );
}

// 404 = henüz paket yok (normal ön-durum) → inline EmptyState (yönlendirme kapalı).
export function getCurrentRatificationPackage(
  transactionId: string,
): Promise<RatificationPackagePublicView> {
  return apiRequest<RatificationPackagePublicView>(
    `/transactions/${encodeURIComponent(transactionId)}/ratification-packages/current`,
    { redirectOnError: false },
  );
}

export function submitRatification(packageId: string): Promise<RatificationOutcome> {
  return apiRequest<RatificationOutcome>(
    `/ratification-packages/${encodeURIComponent(packageId)}/ratifications`,
    { method: "POST", csrf: true, redirectOnError: false },
  );
}
