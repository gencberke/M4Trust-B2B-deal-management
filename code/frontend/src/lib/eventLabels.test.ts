import { describe, expect, it } from "vitest";

import { eventLabel, eventLabels } from "./eventLabels";

describe("eventLabel", () => {
  it("bilinen tipi Türkçe etikete çevirir", () => {
    expect(eventLabel("contract_extracted")).toBe("Sözleşme çözümlendi");
    expect(eventLabel("transaction_settled")).toBe("İşlem tamamlandı");
  });

  it("bilinmeyen tip için ham tipi döndürür", () => {
    expect(eventLabel("some_unknown_event")).toBe("some_unknown_event");
  });

  it("Plan 06 funding event'lerini kapsar", () => {
    expect(eventLabels.funding_required).toBeDefined();
    expect(eventLabels.funding_units_pool_created).toBeDefined();
    expect(eventLabels.funding_units_approved).toBeDefined();
  });
});
