import { apiRequest } from "./client";
import type {
  ExtractionRevisionInput,
  RuleSetVersionHistory,
  RuleSetVersionPublicView,
} from "../types/rules";

export function getRuleSetVersions(transactionId: string): Promise<RuleSetVersionHistory> {
  return apiRequest<RuleSetVersionHistory>(
    `/transactions/${encodeURIComponent(transactionId)}/rule-sets`,
    { redirectOnError: false },
  );
}

export function createRuleRevision(
  transactionId: string,
  versionId: string,
  payload: ExtractionRevisionInput,
): Promise<RuleSetVersionPublicView> {
  return apiRequest<RuleSetVersionPublicView>(
    `/transactions/${encodeURIComponent(transactionId)}/rule-sets/${encodeURIComponent(versionId)}/revisions`,
    { method: "POST", body: payload, csrf: true, redirectOnError: false },
  );
}

export function validateRuleVersion(
  transactionId: string,
  versionId: string,
): Promise<RuleSetVersionPublicView> {
  return apiRequest<RuleSetVersionPublicView>(
    `/transactions/${encodeURIComponent(transactionId)}/rule-sets/${encodeURIComponent(versionId)}/validate`,
    { method: "POST", csrf: true, redirectOnError: false },
  );
}
