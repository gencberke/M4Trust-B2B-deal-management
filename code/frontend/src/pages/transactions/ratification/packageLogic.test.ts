import { describe, expect, it } from "vitest";

import type { CanonicalPackagePayload } from "../../../types/ratification";
import {
  buildSpecFromForm,
  packageReadinessItems,
  RATIFY_NETWORK_WARNING,
  ratifyErrorMessage,
  readinessChecklist,
  scheduleRows,
} from "./packageLogic";

describe("packageReadinessItems", () => {
  it("backend hazırlık kapılarını mevcut projection'lardan aynalar", () => {
    const detail = { state: "awaiting_ratification", extraction: {}, validator: { status: "PASS" } } as never;
    const policy = { tracking_policy: { status: "locked" } } as never;
    const pkg = { status: "open", canonical_payload: { funding_schedule: { milestones: [{}] } } } as never;
    expect(packageReadinessItems(detail, policy, pkg).every((item) => item.ready)).toBe(true);
  });

  it("awaiting_review durumunda blocking review satırını hazır göstermez", () => {
    const items = packageReadinessItems({ state: "awaiting_review", extraction: null, validator: null } as never, null, null);
    expect(items.find((item) => item.key === "reviews")?.ready).toBe(false);
  });
});

describe("readinessChecklist", () => {
  it("bilinen kodları Türkçe satıra çevirir", () => {
    expect(readinessChecklist("TRACKING_POLICY_NOT_LOCKED")).toContain("kilitlenmedi");
    expect(readinessChecklist("PARTICIPANTS_NOT_CONFIRMED")).toContain("onaylanmadı");
    expect(readinessChecklist("BLOCKING_REVIEW")).toContain("inceleme açık");
  });
  it("bilinmeyen kod ham koda düşer", () => {
    expect(readinessChecklist("MYSTERY_CODE")).toContain("MYSTERY_CODE");
  });
});

describe("ratifyErrorMessage", () => {
  it("superseded ve already-complete ayrı mesaj", () => {
    expect(ratifyErrorMessage("PACKAGE_SUPERSEDED")).toContain("yenilendi");
    expect(ratifyErrorMessage("PACKAGE_ALREADY_COMPLETE")).toContain("tamamlanmış");
    expect(ratifyErrorMessage("RATIFICATION_NOT_AUTHORIZED")).toContain("yetkiniz yok");
  });
  it("bilinmeyen kod → genel", () => {
    expect(ratifyErrorMessage("NOPE")).toContain("tamamlanamadı");
  });
});

describe("RATIFY_NETWORK_WARNING", () => {
  it("yenile + güvenli tekrar mesajı içerir", () => {
    expect(RATIFY_NETWORK_WARNING).toContain("yenileyin");
  });
});

describe("scheduleRows", () => {
  const payload: CanonicalPackagePayload = {
    funding_schedule: {
      currency: "TRY",
      total_amount_minor: 10000000,
      milestones: [
        {
          rule_index: 0,
          title: "M1",
          trigger_type: "approval",
          basis_points: 10000,
          amount_minor: 10000000,
          currency: "TRY",
          required_evidence: ["contract"],
          release_mode: "all_or_nothing",
          funding_units: [
            { sequence: 1, amount_minor: 10000000, eligibility_type: "approval", eligibility_payload: { secret: "x" } },
          ],
        },
      ],
    },
  };

  it("milestone+unit satırlarını yalnız izinli tiplenmiş anahtarlarla düzler", () => {
    const rows = scheduleRows(payload);
    expect(rows).toHaveLength(1);
    expect(rows[0].units[0].sequence).toBe(1);
    // eligibility_payload (ham/secret) DÜZ satıra taşınmaz.
    const keys = Object.keys(rows[0].units[0]);
    expect(keys).toEqual(["sequence", "amount_minor", "eligibility_type"]);
    expect(JSON.stringify(rows)).not.toContain("secret");
  });

  it("funding_schedule yoksa boş döner", () => {
    expect(scheduleRows({})).toEqual([]);
  });
});

describe("buildSpecFromForm", () => {
  it("all_or_nothing override üretir", () => {
    const result = buildSpecFromForm([{ rule_index: 0, release_mode: "all_or_nothing", tranche_count: "" }]);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.spec.overrides[0]).toEqual({ rule_index: 0, release_mode: "all_or_nothing" });
  });

  it("fixed_tranches için dilim ≥2 zorunlu", () => {
    expect(buildSpecFromForm([{ rule_index: 0, release_mode: "fixed_tranches", tranche_count: "1" }]).ok).toBe(false);
    const ok = buildSpecFromForm([{ rule_index: 0, release_mode: "fixed_tranches", tranche_count: "3" }]);
    expect(ok.ok).toBe(true);
    if (!ok.ok) return;
    expect(ok.spec.overrides[0]).toEqual({ rule_index: 0, release_mode: "fixed_tranches", tranche_count: 3 });
  });

  it("boş liste → boş overrides", () => {
    const result = buildSpecFromForm([]);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.spec.overrides).toEqual([]);
  });
});
