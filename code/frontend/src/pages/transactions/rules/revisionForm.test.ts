import { describe, expect, it } from "vitest";

import type { RedactedExtraction } from "../../../types/transactions";
import {
  buildRevisionPayload,
  formStateFromExtraction,
  revisionErrorMessage,
} from "./revisionForm";

function extraction(): RedactedExtraction {
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
    risk_flags: ["late"],
    needs_manual_review: false,
  };
}

describe("formStateFromExtraction + buildRevisionPayload", () => {
  it("round-trip: source_quote her zaman omit (null) edilir", () => {
    const state = formStateFromExtraction(extraction());
    const result = buildRevisionPayload(state);
    expect(result.ok).toBe(true);
    if (!result.ok || !result.payload) return;
    expect(result.payload.payment_rules[0].source_quote).toBeNull();
    // Asla boş string veya maskeli metin gönderilmez.
    expect(result.payload.payment_rules[0].source_quote).not.toBe("");
    expect(result.payload.risk_flags).toEqual(["late"]);
    expect(result.payload.commercial_terms.total_amount).toBe(1000);
  });

  it("değişen yüzdeyi coerce eder (sayı)", () => {
    const state = formStateFromExtraction(extraction());
    state.payment_rules[0].percentage = "50";
    const result = buildRevisionPayload(state);
    expect(result.ok).toBe(true);
    if (!result.ok || !result.payload) return;
    expect(result.payload.payment_rules[0].percentage).toBe(50);
  });

  it("sayısal olmayan tutarı reddeder", () => {
    const state = formStateFromExtraction(extraction());
    state.total_amount = "abc";
    expect(buildRevisionPayload(state).ok).toBe(false);
  });

  it("geçersiz tetikleyici/kanıt/para birimini reddeder", () => {
    const s1 = formStateFromExtraction(extraction());
    s1.payment_rules[0].trigger = "wat";
    expect(buildRevisionPayload(s1).ok).toBe(false);

    const s2 = formStateFromExtraction(extraction());
    s2.payment_rules[0].required_evidence = "contract, hologram";
    expect(buildRevisionPayload(s2).ok).toBe(false);

    const s3 = formStateFromExtraction(extraction());
    s3.currency = "GBP";
    expect(buildRevisionPayload(s3).ok).toBe(false);
  });

  it("geçersiz tarih biçimini reddeder", () => {
    const state = formStateFromExtraction(extraction());
    state.delivery_deadline = "01/08/2026";
    expect(buildRevisionPayload(state).ok).toBe(false);
  });
});

describe("revisionErrorMessage", () => {
  it("stale ve after-ratification kodları ayrı mesaj", () => {
    expect(revisionErrorMessage("STALE_RULE_SET_VERSION")).toContain("güncel değil");
    expect(revisionErrorMessage("RULE_REVISION_AFTER_RATIFICATION")).toContain("Onay sonrası");
    expect(revisionErrorMessage("RULE_REVISION_SOURCE_QUOTE_REQUIRED")).toContain("alıntı");
  });
  it("bilinmeyen kod → genel", () => {
    expect(revisionErrorMessage("NOPE")).toContain("tamamlanamadı");
  });
});
