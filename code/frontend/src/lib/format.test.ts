import { describe, expect, it } from "vitest";

import {
  formatAmountMajor,
  formatAmountMinor,
  formatDateTime,
  formatPercentBps,
  formatRatioPercent,
  shortId,
} from "./format";

describe("formatDateTime", () => {
  it("geçersiz ISO için — döner", () => {
    expect(formatDateTime("not-a-date")).toBe("—");
    expect(formatDateTime("")).toBe("—");
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime(undefined)).toBe("—");
  });

  it("geçerli ISO'yu biçimlendirir", () => {
    const out = formatDateTime("2026-07-12T10:30:00Z");
    expect(out).not.toBe("—");
    expect(out.length).toBeGreaterThan(0);
  });
});

describe("formatAmountMinor", () => {
  it("kuruşu bölerek para birimiyle gösterir", () => {
    expect(formatAmountMinor(150000, "TRY")).toContain("1.500");
  });

  it("bilinmeyen para birimi düz sayı + koda düşer", () => {
    const out = formatAmountMinor(150000, "ZZZ");
    expect(out).toContain("ZZZ");
    expect(out).toContain("1.500");
  });

  it("boş para birimi düz sayı döner", () => {
    expect(formatAmountMinor(150000, "")).toContain("1.500");
  });

  it("null/NaN için — döner", () => {
    expect(formatAmountMinor(null, "TRY")).toBe("—");
    expect(formatAmountMinor(Number.NaN, "TRY")).toBe("—");
  });
});

describe("formatAmountMajor", () => {
  it("tam birimi bölmeden gösterir", () => {
    const out = formatAmountMajor(1500, "TRY");
    expect(out).toContain("1.500");
  });

  it("bilinmeyen para birimi kod ekler", () => {
    expect(formatAmountMajor(1500, "ZZZ")).toContain("ZZZ");
  });

  it("null için — döner", () => {
    expect(formatAmountMajor(null, "TRY")).toBe("—");
  });
});

describe("formatPercentBps", () => {
  it("10000 bps → %100", () => {
    expect(formatPercentBps(10000)).toBe("%100");
  });
  it("null → —", () => {
    expect(formatPercentBps(null)).toBe("—");
  });
});

describe("formatRatioPercent", () => {
  it("0.9 → %90", () => {
    expect(formatRatioPercent(0.9)).toBe("%90");
  });
  it("null → —", () => {
    expect(formatRatioPercent(null)).toBe("—");
  });
});

describe("shortId", () => {
  it("uzun id'yi kısaltır", () => {
    expect(shortId("abcdefghijkl")).toBe("abcdefgh");
  });
  it("kısa id'yi olduğu gibi bırakır", () => {
    expect(shortId("abc")).toBe("abc");
  });
});
