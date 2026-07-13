import { describe, expect, it } from "vitest";

import type { TransactionEvent } from "../../types/transactions";
import { safeEventItems, shouldPoll } from "./overviewProjection";

describe("shouldPoll", () => {
  it("yalnız uploaded/extracting'te poll yapar", () => {
    expect(shouldPoll("uploaded")).toBe(true);
    expect(shouldPoll("extracting")).toBe(true);
    expect(shouldPoll("active")).toBe(false);
    expect(shouldPoll("awaiting_review")).toBe(false);
    expect(shouldPoll("settled")).toBe(false);
  });
});

describe("safeEventItems", () => {
  it("izinli skalar alanları alır, hassas alanları düşürür", () => {
    const events: TransactionEvent[] = [
      {
        id: 1,
        event_type: "payment_decision_created",
        source: "system",
        created_at: "2026-07-12T00:00:00Z",
        payload: {
          action: "hold",
          manual_review_required: true,
          finding_codes: ["A", "B"],
          // hassas — asla gösterilmemeli:
          manager_token: "secret-token",
          raw: "ham markdown",
          markdown: "# gizli",
          mask_map: { x: "y" },
        },
      },
    ];

    const [item] = safeEventItems(events);
    const labels = item.details.map((d) => d.label);
    expect(labels).toContain("action");
    expect(labels).toContain("manual_review_required");
    expect(labels).toContain("finding_codes");
    expect(labels).not.toContain("manager_token");
    expect(labels).not.toContain("raw");
    expect(labels).not.toContain("markdown");
    expect(labels).not.toContain("mask_map");

    // Değerlerin hiçbirinde sızıntı yok.
    const serialized = JSON.stringify(item);
    expect(serialized).not.toContain("secret-token");
    expect(serialized).not.toContain("ham markdown");
  });

  it("bilinen etiket ve tonu uygular; null payload'ı tolere eder", () => {
    const [item] = safeEventItems([
      {
        id: 2,
        event_type: "transaction_settled",
        source: "system",
        created_at: "2026-07-12T00:00:00Z",
        payload: null,
      },
    ]);
    expect(item.title).toBe("İşlem tamamlandı");
    expect(item.tone).toBe("success");
    expect(item.details).toHaveLength(0);
  });

  it("bilinmeyen event tipini ham tip + neutral ton ile gösterir", () => {
    const [item] = safeEventItems([
      {
        id: 3,
        event_type: "mystery_event",
        source: "system",
        created_at: "2026-07-12T00:00:00Z",
        payload: {},
      },
    ]);
    expect(item.title).toBe("mystery_event");
    expect(item.tone).toBe("neutral");
  });
});
