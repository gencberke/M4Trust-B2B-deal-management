import { describe, expect, it } from "vitest";

import {
  participantStatusMap,
  resolveStatus,
  transactionStateMap,
  validatorStatusMap,
} from "./statusMaps";

describe("resolveStatus", () => {
  it("bilinen state için etiket + ton döner", () => {
    const result = resolveStatus(transactionStateMap, "active");
    expect(result).toEqual({ label: "Aktif", tone: "success" });
  });

  it("bilinmeyen state için nötr ham etiket döner", () => {
    expect(resolveStatus(transactionStateMap, "quantum_state")).toEqual({
      label: "quantum_state",
      tone: "neutral",
    });
  });

  it("null/undefined için nötr — döner", () => {
    expect(resolveStatus(transactionStateMap, null)).toEqual({ label: "—", tone: "neutral" });
    expect(resolveStatus(transactionStateMap, undefined)).toEqual({ label: "—", tone: "neutral" });
  });
});

describe("declared status maps", () => {
  it("her transaction state anahtarı geçerli descriptor döndürür", () => {
    for (const key of Object.keys(transactionStateMap)) {
      const d = resolveStatus(transactionStateMap, key);
      expect(d.label.length).toBeGreaterThan(0);
      expect(["info", "success", "warning", "danger", "neutral"]).toContain(d.tone);
    }
  });

  it("participant ve validator haritaları çözülür", () => {
    expect(resolveStatus(participantStatusMap, "confirmed").tone).toBe("success");
    expect(resolveStatus(validatorStatusMap, "REJECT").tone).toBe("danger");
  });
});
