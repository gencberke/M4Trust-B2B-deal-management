"""Account v2 state transition helper (Plan 04 / Wave B / Faz 4D)."""

from __future__ import annotations

import sqlite3
from collections.abc import Collection

from backend.app.services.access_control import ActorContext


class AccountLifecycleError(Exception):
    """Account lifecycle transition fail-closed hatası."""


def transition_account_state(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    expected_states: Collection[str],
    target_state: str,
    actor_context: ActorContext,
    reason_code: str,
) -> bool:
    """Account v2 state'i conditional update ile değiştirir; commit çağırana aittir."""
    del actor_context, reason_code
    row = conn.execute(
        "SELECT lifecycle_version, state FROM transactions WHERE id = ?",
        (transaction_id,),
    ).fetchone()
    if row is None:
        raise AccountLifecycleError("Transaction bulunamadı.")
    if row["lifecycle_version"] != "account_v2":
        raise AccountLifecycleError("Legacy transaction account state transition'a giremez.")
    if row["state"] == target_state:
        return False
    if row["state"] not in set(expected_states):
        raise AccountLifecycleError(
            f"Beklenmeyen account state: {row['state']} (target={target_state})."
        )
    cursor = conn.execute(
        "UPDATE transactions SET state = ? WHERE id = ? AND lifecycle_version = 'account_v2' "
        "AND state = ?",
        (target_state, transaction_id, row["state"]),
    )
    if cursor.rowcount != 1:
        raise AccountLifecycleError("Account state eşzamanlı olarak değişti.")
    return True
