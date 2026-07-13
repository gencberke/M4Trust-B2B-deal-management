import { describe, expect, it } from "vitest";

import {
  packageStatusMap,
  participantStatusMap,
  policyStatusMap,
  resolveStatus,
  reviewSeverityMap,
  reviewStatusMap,
  ruleSetStatusMap,
  validatorStatusMap,
} from "./statusMaps";

describe("resolveStatus", () => {
  it("null/undefined için nötr — döner", () => {
    expect(resolveStatus(reviewStatusMap, null)).toEqual({ label: "—", tone: "neutral" });
    expect(resolveStatus(reviewStatusMap, undefined)).toEqual({ label: "—", tone: "neutral" });
  });
});

describe("declared status maps", () => {
  it("participant ve validator haritaları çözülür", () => {
    expect(resolveStatus(participantStatusMap, "confirmed").tone).toBe("success");
    expect(resolveStatus(validatorStatusMap, "REJECT").tone).toBe("danger");
  });

  it("PR2 review/package/policy haritaları çözülür", () => {
    expect(resolveStatus(reviewStatusMap, "open").tone).toBe("warning");
    expect(resolveStatus(reviewSeverityMap, "blocking").tone).toBe("danger");
    expect(resolveStatus(packageStatusMap, "complete").tone).toBe("success");
    expect(resolveStatus(packageStatusMap, "superseded").tone).toBe("warning");
    expect(resolveStatus(policyStatusMap, "locked").tone).toBe("success");
    expect(resolveStatus(ruleSetStatusMap, "ratifiable").tone).toBe("success");
  });

  it("bilinmeyen review status nötr ham etikete düşer", () => {
    expect(resolveStatus(reviewStatusMap, "mystery")).toEqual({ label: "mystery", tone: "neutral" });
  });
});
