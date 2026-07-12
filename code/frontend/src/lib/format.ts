const EMPTY = "—";

/** ISO tarihini Türkçe yerel biçimde gösterir; geçersiz girdi → "—". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return EMPTY;
  return new Intl.DateTimeFormat("tr-TR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

/**
 * Minor birimdeki (kuruş) tutarı görüntüler. Bölme yalnız gösterim içindir —
 * frontend bunun ötesinde finansal aritmetik yapmaz. Bilinmeyen para birimi →
 * düz sayı + kod.
 */
export function formatAmountMinor(
  amountMinor: number | null | undefined,
  currency: string | null | undefined,
): string {
  if (amountMinor == null || Number.isNaN(amountMinor)) return EMPTY;
  const major = amountMinor / 100;
  const code = (currency ?? "").trim().toUpperCase();
  if (!code) {
    return new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2 }).format(major);
  }
  try {
    return new Intl.NumberFormat("tr-TR", { style: "currency", currency: code }).format(major);
  } catch {
    return `${new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2 }).format(major)} ${code}`;
  }
}

/**
 * Extraction'dan gelen major-birim tutarı görüntüler (total_amount zaten tam
 * birimdir; /100 yapılmaz). Bilinmeyen para birimi → düz sayı + kod.
 */
export function formatAmountMajor(
  amount: number | null | undefined,
  currency: string | null | undefined,
): string {
  if (amount == null || Number.isNaN(amount)) return EMPTY;
  const code = (currency ?? "").trim().toUpperCase();
  if (!code) {
    return new Intl.NumberFormat("tr-TR").format(amount);
  }
  try {
    return new Intl.NumberFormat("tr-TR", { style: "currency", currency: code }).format(amount);
  } catch {
    return `${new Intl.NumberFormat("tr-TR").format(amount)} ${code}`;
  }
}

/** Basis point → yüzde metni (10000 bps = %100). Geçersiz girdi → "—". */
export function formatPercentBps(basisPoints: number | null | undefined): string {
  if (basisPoints == null || Number.isNaN(basisPoints)) return EMPTY;
  return `%${new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 2 }).format(basisPoints / 100)}`;
}

/** Extraction confidence gibi 0–1 oranını yüzde olarak gösterir. */
export function formatRatioPercent(ratio: number | null | undefined): string {
  if (ratio == null || Number.isNaN(ratio)) return EMPTY;
  return `%${new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 0 }).format(ratio * 100)}`;
}

/** İşlem kimliğinin kısa, gösterilebilir ön eki (deep-link'lerde tam id kullanılır). */
export function shortId(id: string, length = 8): string {
  return id.length <= length ? id : id.slice(0, length);
}
