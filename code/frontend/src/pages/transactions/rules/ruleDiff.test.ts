import { describe, expect, it } from "vitest";

import type { RedactedExtraction } from "../../../types/transactions";
import { diffExtraction } from "./ruleDiff";

function base(): RedactedExtraction {
  return {
    contract_id: "c-1",
    parties: { buyer: { name: "A" }, seller: { name: "B" } },
    commercial_terms: {
      currency: "TRY",
      total_amount: 1000,
      goods: [{ name: "Pompa", quantity: 10, unit: "adet" }],
      delivery_deadline: "2026-08-01",
    },
    payment_rules: [
      { milestone: "M1", trigger: "approval", percentage: 100, required_evidence: ["contract"], confidence: 0.9 },
    ],
    risk_flags: [],
    needs_manual_review: false,
  };
}

describe("diffExtraction", () => {
  it("null girdilerde boş döner", () => {
    expect(diffExtraction(null, base())).toEqual([]);
    expect(diffExtraction(base(), null)).toEqual([]);
  });

  it("değişen kural yüzdesini yakalar", () => {
    const b = base();
    b.payment_rules[0].percentage = 50;
    const rows = diffExtraction(base(), b);
    const row = rows.find((r) => r.path === "payment_rules[0].percentage");
    expect(row).toBeDefined();
    expect(row?.kind).toBe("changed");
    expect(row?.before).toBe("100");
    expect(row?.after).toBe("50");
  });

  it("eklenen mal kalemini added olarak işaretler", () => {
    const b = base();
    b.commercial_terms.goods.push({ name: "Vana", quantity: 2, unit: "adet" });
    const rows = diffExtraction(base(), b);
    const added = rows.find((r) => r.path === "goods[1]");
    expect(added?.kind).toBe("added");
    expect(added?.after).toContain("Vana");
  });

  it("kaldırılan risk flag'ı changed (liste) olarak yansıtır", () => {
    const a = base();
    a.risk_flags = ["late_delivery"];
    const rows = diffExtraction(a, base());
    const row = rows.find((r) => r.path === "risk_flags");
    expect(row?.before).toContain("late_delivery");
    expect(row?.after).toBe("—");
  });

  it("değişiklik yoksa boş döner", () => {
    expect(diffExtraction(base(), base())).toEqual([]);
  });
});
