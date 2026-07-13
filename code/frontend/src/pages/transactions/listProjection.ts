import { lifecycleFor } from "../../lib/lifecycle";
import type { TransactionListItem } from "../../types/transactions";

export interface TransactionGroup { key: string; label: string; transactions: TransactionListItem[]; }
export interface TransactionStats { total: number; active: number; awaitingAction: number; settled: number; }

export function groupTransactionsByState(items: TransactionListItem[]): TransactionGroup[] {
  const groups = new Map<string, TransactionGroup>();
  for (const tx of items) {
    const lifecycle = lifecycleFor(tx.state);
    const current = groups.get(tx.state) ?? { key: tx.state, label: lifecycle.label, transactions: [] };
    current.transactions.push(tx);
    groups.set(tx.state, current);
  }
  return [...groups.values()].sort((a, b) => lifecycleFor(b.key).stepIndex - lifecycleFor(a.key).stepIndex);
}

export function transactionStats(items: TransactionListItem[]): TransactionStats {
  return {
    total: items.length,
    active: items.filter((tx) => tx.state === "active").length,
    awaitingAction: items.filter((tx) => ["awaiting_review", "awaiting_approval", "awaiting_ratification"].includes(tx.state)).length,
    settled: items.filter((tx) => tx.state === "settled").length,
  };
}
