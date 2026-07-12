import { describe, expect, it } from "vitest";

import type { ReviewCaseWithActions } from "../../../types/reviews";
import {
  isResolveAction,
  reviewActionErrorMessage,
  safeActionPayloadEntries,
  splitCasesBySource,
} from "./rulesLogic";

function caseItem(sourceType: string, id: string): ReviewCaseWithActions {
  return {
    case: {
      id,
      transaction_id: "tx-1",
      phase: "pre_ratification",
      source_type: sourceType,
      source_id: null,
      reason_code: "R",
      title: "t",
      description: "d",
      severity: "warning",
      status: "open",
      assigned_to_user_id: null,
      opened_by_actor_type: "system",
      opened_by_user_id: null,
      resolved_by_user_id: null,
      resolution_code: null,
      resolution_note: null,
      created_at: "2026-07-12T00:00:00Z",
      resolved_at: null,
    },
    actions: [],
  };
}

describe("safeActionPayloadEntries", () => {
  it("izinli anahtarları alır, hassas anahtarları düşürür", () => {
    const entries = safeActionPayloadEntries({
      comment: "merhaba",
      resolution_code: "VIDEO_FALSE_POSITIVE",
      operation_type: "undo",
      // hassas:
      token: "secret",
      raw: "ham",
      manager_token: "x",
    });
    const labels = entries.map((e) => e.label);
    expect(labels).toContain("comment");
    expect(labels).toContain("resolution_code");
    expect(labels).toContain("operation_type");
    expect(labels).not.toContain("token");
    expect(labels).not.toContain("raw");
    expect(labels).not.toContain("manager_token");
    expect(JSON.stringify(entries)).not.toContain("secret");
  });

  it("null payload → boş", () => {
    expect(safeActionPayloadEntries(null)).toEqual([]);
  });
});

describe("splitCasesBySource", () => {
  it("party_mismatch case'lerini ayırır ama others hepsini tutar", () => {
    const cases = [caseItem("party_mismatch", "a"), caseItem("validator", "b")];
    const { partyMismatch, others } = splitCasesBySource(cases);
    expect(partyMismatch.map((c) => c.id)).toEqual(["a"]);
    expect(others).toHaveLength(2);
  });
});

describe("reviewActionErrorMessage", () => {
  it("bilinen kodları ayrı mesaja çevirir", () => {
    expect(reviewActionErrorMessage("REVIEW_COMMENT_REJECTED")).toContain("Yorum reddedildi");
    expect(reviewActionErrorMessage("REVIEW_CASE_CLOSED")).toContain("kapalı");
    expect(reviewActionErrorMessage("REVIEW_ACTION_NOT_ALLOWED")).toContain("uygulanamaz");
    expect(reviewActionErrorMessage("REVIEW_RESOLUTION_PRECONDITION_FAILED")).toContain("ön koşul");
  });
  it("bilinmeyen kod → genel mesaj", () => {
    expect(reviewActionErrorMessage("NOPE")).toContain("tamamlanamadı");
  });
});

describe("isResolveAction", () => {
  it("resolve aksiyonları için true", () => {
    expect(isResolveAction("resolve_continue")).toBe(true);
    expect(isResolveAction("resolve_reject")).toBe(true);
    expect(isResolveAction("comment")).toBe(false);
  });
});
