import { describe, expect, it } from "vitest";
import { groupTransactionsByState, transactionStats } from "./listProjection";
import type { TransactionListItem } from "../../types/transactions";
const tx = (id: string, state: TransactionListItem["state"]): TransactionListItem => ({ id, state, created_at: "2026-07-13T00:00:00Z", buyer_name: null, seller_name: null });
describe("transaction list projection", () => {
  it("işlemleri state'e göre gruplar ve ileri adımı önce sıralar", () => { const groups = groupTransactionsByState([tx("1", "active"), tx("2", "awaiting_review"), tx("3", "active")]); expect(groups.map((g) => [g.key, g.transactions.length])).toEqual([["active", 2], ["awaiting_review", 1]]); });
  it("stat kart sayılarını tek geçişte türetir", () => { expect(transactionStats([tx("1", "active"), tx("2", "awaiting_ratification"), tx("3", "settled")])).toEqual({ total: 3, active: 1, awaitingAction: 1, settled: 1 }); });
});
