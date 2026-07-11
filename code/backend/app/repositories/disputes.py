"""`disputes`/`dispute_actions` satır/sorgu erişimi (Plan 05 / Faz 5B).

Yalnız caller connection'ını kullanır; commit/rollback/connect yapmaz.
`dispute_actions` append-only'dir (DB trigger reddeder) — update fonksiyonu
sunulmaz. `disputes`'ta yalnız durum/çözüm alanlarını değiştiren dar bir
`update_status` sunulur; diğer alanlar (opened_by_*, reason_code, description,
created_at) hiçbir fonksiyon tarafından değiştirilmez.
"""

from __future__ import annotations

from sqlite3 import Connection, Row


def insert_dispute(
    conn: Connection,
    *,
    id: str,
    transaction_id: str,
    milestone_id: str | None,
    opened_by_user_id: str,
    opened_by_entity_id: str,
    reason_code: str,
    description: str,
    created_at: str,
) -> None:
    conn.execute(
        """INSERT INTO disputes (
            id, transaction_id, milestone_id, opened_by_user_id, opened_by_entity_id,
            reason_code, description, status, resolution_code, resolved_by_user_id,
            created_at, resolved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', NULL, NULL, ?, NULL)""",
        (
            id,
            transaction_id,
            milestone_id,
            opened_by_user_id,
            opened_by_entity_id,
            reason_code,
            description,
            created_at,
        ),
    )


def get_by_id(conn: Connection, dispute_id: str) -> Row | None:
    return conn.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,)).fetchone()


def get_open_for_scope(conn: Connection, *, transaction_id: str, milestone_id: str | None) -> Row | None:
    return conn.execute(
        "SELECT * FROM disputes WHERE transaction_id = ? AND COALESCE(milestone_id, '') = ? "
        "AND status NOT IN ('resolved', 'cancelled')",
        (transaction_id, milestone_id or ""),
    ).fetchone()


def list_for_transaction(conn: Connection, transaction_id: str) -> list[Row]:
    return conn.execute(
        "SELECT * FROM disputes WHERE transaction_id = ? ORDER BY created_at ASC",
        (transaction_id,),
    ).fetchall()


def has_open_dispute(conn: Connection, *, transaction_id: str, milestone_id: str | None) -> bool:
    """`milestone_id=None`: transaction'daki herhangi bir açık dispute.
    `milestone_id` verilirse: o milestone'a özel açık dispute VEYA transaction-wide
    (milestone_id IS NULL) açık dispute -- ikisi de release'i bloklar."""
    if milestone_id is None:
        row = conn.execute(
            "SELECT 1 FROM disputes WHERE transaction_id = ? AND status NOT IN ('resolved', 'cancelled') "
            "LIMIT 1",
            (transaction_id,),
        ).fetchone()
        return row is not None
    row = conn.execute(
        "SELECT 1 FROM disputes WHERE transaction_id = ? AND status NOT IN ('resolved', 'cancelled') "
        "AND (milestone_id = ? OR milestone_id IS NULL) LIMIT 1",
        (transaction_id, milestone_id),
    ).fetchone()
    return row is not None


def update_status(
    conn: Connection,
    *,
    dispute_id: str,
    status: str,
    resolution_code: str | None = None,
    resolved_by_user_id: str | None = None,
    resolved_at: str | None = None,
) -> None:
    conn.execute(
        "UPDATE disputes SET status = ?, resolution_code = ?, resolved_by_user_id = ?, "
        "resolved_at = ? WHERE id = ?",
        (status, resolution_code, resolved_by_user_id, resolved_at, dispute_id),
    )


def append_action(
    conn: Connection,
    *,
    id: str,
    dispute_id: str,
    actor_user_id: str,
    acting_entity_id: str,
    action: str,
    evidence_id: str | None,
    payload_json: str | None,
    created_at: str,
) -> None:
    conn.execute(
        """INSERT INTO dispute_actions (
            id, dispute_id, actor_user_id, acting_entity_id, action, evidence_id,
            payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, dispute_id, actor_user_id, acting_entity_id, action, evidence_id, payload_json, created_at),
    )


def list_actions(conn: Connection, dispute_id: str) -> list[Row]:
    return conn.execute(
        "SELECT * FROM dispute_actions WHERE dispute_id = ? ORDER BY created_at ASC",
        (dispute_id,),
    ).fetchall()
