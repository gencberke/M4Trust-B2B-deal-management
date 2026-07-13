import { eventLabel } from "../../lib/eventLabels";
import type { StatusTone } from "../../lib/statusMaps";
import type { AccountState, TransactionEvent } from "../../types/transactions";

/** Yalnız yükleme/çıkarım sürerken poll yapılır. */
export function shouldPoll(state: AccountState): boolean {
  return state === "uploaded" || state === "extracting";
}

// Event payload'ından yalnız izinli, hassas olmayan skalar alanlar gösterilir.
// token/raw/markdown/mask haritası gibi alanlar ASLA DOM'a dökülmez (master §9.6).
const ALLOWED_PAYLOAD_KEYS = [
  "status",
  "finding_codes",
  "funding_unit_count",
  "milestone_count",
  "action",
  "manual_review_required",
] as const;

const EVENT_TONE: Record<string, StatusTone> = {
  transaction_settled: "success",
  funding_units_approved: "success",
  seller_approved: "success",
  buyer_approved: "success",
  rules_validated: "info",
  contract_extracted: "info",
  dispute_opened: "danger",
  payment_decision_created: "info",
};

export interface OverviewEventItem {
  id: number;
  title: string;
  tone: StatusTone;
  timestamp: string;
  details: { label: string; value: string }[];
}

function isScalar(value: unknown): value is string | number | boolean {
  return (
    typeof value === "string" || typeof value === "number" || typeof value === "boolean"
  );
}

/** Event listesini Timeline öğelerine çevirir; payload'dan yalnız allowlist skalarları. */
export function safeEventItems(events: TransactionEvent[]): OverviewEventItem[] {
  return events.map((event) => {
    const details: { label: string; value: string }[] = [];
    const payload = event.payload ?? {};
    for (const key of ALLOWED_PAYLOAD_KEYS) {
      if (!Object.prototype.hasOwnProperty.call(payload, key)) continue;
      const raw = payload[key];
      if (isScalar(raw)) {
        details.push({ label: key, value: String(raw) });
      } else if (Array.isArray(raw) && raw.every(isScalar)) {
        details.push({ label: key, value: raw.join(", ") });
      }
    }
    return {
      id: event.id,
      title: eventLabel(event.event_type),
      tone: EVENT_TONE[event.event_type] ?? "neutral",
      timestamp: event.created_at,
      details,
    };
  });
}
