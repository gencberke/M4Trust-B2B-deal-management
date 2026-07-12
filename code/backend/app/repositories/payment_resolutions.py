"""Undo/refund resolution persistence seam (Plan 07)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_by_id(conn: sqlite3.Connection, resolution_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM payment_resolutions WHERE id = ?", (resolution_id,)
    ).fetchone()


def get_by_idempotency(
    conn: sqlite3.Connection, idempotency_key: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM payment_resolutions WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()


def get_by_unit_and_operation(
    conn: sqlite3.Connection, *, funding_unit_id: str, operation_type: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM payment_resolutions WHERE funding_unit_id = ? "
        "AND operation_type = ? ORDER BY created_at DESC LIMIT 1",
        (funding_unit_id, operation_type),
    ).fetchone()


def list_for_transaction(conn: sqlite3.Connection, transaction_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM payment_resolutions WHERE transaction_id = "
        "? ORDER BY created_at ASC, id ASC",
        (transaction_id,),
    ).fetchall()


def insert(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    funding_unit_id: str,
    review_case_id: str,
    operation_type: str,
    idempotency_key: str,
    requested_by_user_id: str,
    requested_by_entity_id: str,
) -> sqlite3.Row:
    resolution_id = uuid4().hex
    now = _now()
    conn.execute(
        """INSERT INTO payment_resolutions (
            id, transaction_id, funding_unit_id, review_case_id, operation_type,
            status, idempotency_key, requested_by_user_id, requested_by_entity_id,
            executed_by_user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'requested', ?, ?, ?, NULL, ?, ?)""",
        (
            resolution_id,
            transaction_id,
            funding_unit_id,
            review_case_id,
            operation_type,
            idempotency_key,
            requested_by_user_id,
            requested_by_entity_id,
            now,
            now,
        ),
    )
    return get_by_id(conn, resolution_id)  # type: ignore[return-value]


def update_status(
    conn: sqlite3.Connection,
    resolution_id: str,
    *,
    status: str,
    executed_by_user_id: str | None = None,
) -> sqlite3.Row:
    conn.execute(
        "UPDATE payment_resolutions SET status = ?, executed_by_user_id = "
        "COALESCE(?, executed_by_user_id), updated_at = ? WHERE id = ?",
        (status, executed_by_user_id, _now(), resolution_id),
    )
    row = get_by_id(conn, resolution_id)
    if row is None:
        raise KeyError(f"Payment resolution bulunamadı: {resolution_id}")
    return row


def claim_executing(
    conn: sqlite3.Connection,
    resolution_id: str,
    *,
    from_statuses: tuple[str, ...],
) -> bool:
    """Atomik compare-and-set: yalnız `status IN from_statuses` iken `executing`e
    geçer. `rowcount == 1` dönerse çağıran provider'ı çağırmaya yetkilidir;
    aksi hâlde başka bir çağrı zaten claim etmiştir (concurrent execute guard,
    Plan 07 review remediation)."""

    placeholders = ",".join("?" for _ in from_statuses)
    cursor = conn.execute(
        f"UPDATE payment_resolutions SET status = 'executing', updated_at = ? "
        f"WHERE id = ? AND status IN ({placeholders})",
        (_now(), resolution_id, *from_statuses),
    )
    return cursor.rowcount == 1


def list_approvals(
    conn: sqlite3.Connection, resolution_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM payment_resolution_approvals "
        "WHERE resolution_id = ? ORDER BY created_at",
        (resolution_id,),
    ).fetchall()


def get_approval(
    conn: sqlite3.Connection, *, resolution_id: str, participant_role: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM payment_resolution_approvals "
        "WHERE resolution_id = ? AND participant_role = ?",
        (resolution_id, participant_role),
    ).fetchone()


def insert_approval(
    conn: sqlite3.Connection,
    *,
    resolution_id: str,
    participant_role: str,
    user_id: str,
    acting_entity_id: str,
) -> sqlite3.Row:
    approval_id = uuid4().hex
    conn.execute(
        """INSERT INTO payment_resolution_approvals (
            id, resolution_id, participant_role, user_id, acting_entity_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            approval_id,
            resolution_id,
            participant_role,
            user_id,
            acting_entity_id,
            _now(),
        ),
    )
    return conn.execute(
        "SELECT * FROM payment_resolution_approvals WHERE id = ?", (approval_id,)
    ).fetchone()
