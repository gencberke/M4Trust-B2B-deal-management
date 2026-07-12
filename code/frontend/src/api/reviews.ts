import { apiRequest } from "./client";
import type {
  ReviewAction,
  ReviewActionRequest,
  ReviewCaseWithActions,
} from "../types/reviews";

export function listReviews(transactionId: string): Promise<ReviewCaseWithActions[]> {
  return apiRequest<ReviewCaseWithActions[]>(
    `/transactions/${encodeURIComponent(transactionId)}/reviews`,
  );
}

export function submitReviewAction(
  reviewCaseId: string,
  body: ReviewActionRequest,
): Promise<ReviewAction> {
  return apiRequest<ReviewAction>(
    `/reviews/${encodeURIComponent(reviewCaseId)}/actions`,
    { method: "POST", body, csrf: true, redirectOnError: false },
  );
}
