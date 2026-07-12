import { describe, expect, it } from "vitest";
import { parsePolicyConflict, policyConflictMessage, reasonCodeLabel } from "./policyLogic";

describe("policy logic", () => {
  it("parses direct and wrapped conflict objects", () => {
    const value = { code: "POLICY_CONTRACT_CONFLICT", message: "x", conflicts: ["VIDEO_REQUIRED", 1] };
    expect(parsePolicyConflict(value)?.conflicts).toEqual(["VIDEO_REQUIRED"]);
    expect(parsePolicyConflict({ detail: value })?.code).toBe("POLICY_CONTRACT_CONFLICT");
  });
  it("rejects string detail and maps conflict copy", () => {
    expect(parsePolicyConflict("locked")).toBeNull();
    expect(policyConflictMessage("POLICY_CONTRACT_CONFLICT")).toContain("Sözleşme");
    expect(policyConflictMessage("UNKNOWN")).toContain("yenileyip");
  });
  it("maps reason codes and preserves unknown codes", () => {
    expect(reasonCodeLabel("PHYSICAL_GOODS")).toBe("Fiziksel mal teslimi");
    expect(reasonCodeLabel("NEW_REASON")).toBe("NEW_REASON");
  });
});
