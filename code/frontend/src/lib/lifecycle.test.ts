import { describe, expect, it } from "vitest";
import { LIFECYCLE_STEPS, lifecycleFor, lifecycleSectionState, transactionStateMap, type LifecycleRole } from "./lifecycle";
import { resolveStatus } from "./statusMaps";
const states = ["preparation", "uploaded", "extracting", "awaiting_review", "awaiting_approval", "awaiting_ratification", "funding_pending", "active", "settled", "rejected", "cancelled"] as const;
const roles: LifecycleRole[] = ["buyer", "seller", "manager", "reviewer", "unknown"];
describe("lifecycleFor", () => {
  it("her canonical state × rol için geçerli adım ve aksiyon üretir", () => { for (const state of states) for (const role of roles) { const result = lifecycleFor(state, role); expect(result.stepLabel).toBe(LIFECYCLE_STEPS[result.stepIndex]); expect(result.description.length).toBeGreaterThan(0); expect(result.nextAction.label.length).toBeGreaterThan(0); } });
  it("awaiting_review reviewer'ı Kurallar'a yönlendirir, tarafları bekletir", () => { expect(lifecycleFor("awaiting_review", "reviewer").nextAction).toMatchObject({ targetSection: "rules", role: "reviewer" }); expect(lifecycleFor("awaiting_review", "buyer").nextAction).toMatchObject({ role: "counterparty", blockedReason: "Platform incelemesi bekleniyor." }); });
  it("bilinmeyen state'i görünür nötr fallback'e düşürür", () => { expect(lifecycleFor("quantum_state", "buyer").label).toBe("quantum_state"); expect(resolveStatus(transactionStateMap, "quantum_state")).toEqual({ label: "quantum_state", tone: "neutral" }); });
});

describe("lifecycleSectionState", () => {
  it("hedef sekmeyi action, geçmişi done, geleceği waiting+muted türetir", () => {
    const lifecycle = lifecycleFor("awaiting_ratification", "buyer");
    expect(lifecycleSectionState("ratification", lifecycle)).toEqual({ badge: "action", muted: false });
    expect(lifecycleSectionState("parties", lifecycle)).toEqual({ badge: "done", muted: false });
    expect(lifecycleSectionState("fulfillment", lifecycle)).toEqual({ badge: "waiting", muted: true });
  });
});
