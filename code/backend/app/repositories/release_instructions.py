"""Release-instruction repository seam reserved for Plan 06C."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_by_unit_and_operation(
    conn: sqlite3.Connection, *, funding_unit_id: str, operation_type: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM release_instructions WHERE funding_unit_id = ? AND operation_type = ?",
        (funding_unit_id, operation_type),
    ).fetchone()


def insert(
    conn: sqlite3.Connection,
    *,
    funding_unit_id: str,
    provider_payment_id: str,
    idempotency_key: str,
    amount_minor: int,
    currency: str,
    provider: str,
    provider_reference: str | None = None,
    operation_type: str = "approve_pool_payment",
) -> sqlite3.Row:
    now = _now()
    instruction_id = uuid4().hex
    conn.execute(
        """INSERT INTO release_instructions (
            id, funding_unit_id, provider_payment_id, operation_type,
            amount_minor, currency, idempotency_key, status, provider,
            provider_reference, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'created', ?, ?, ?, ?)""",
        (
            instruction_id,
            funding_unit_id,
            provider_payment_id,
            operation_type,
            amount_minor,
            currency,
            idempotency_key,
            provider,
            provider_reference,
            now,
            now,
        ),
    )
    return conn.execute(
        "SELECT * FROM release_instructions WHERE id = ?", (instruction_id,)
    ).fetchone()


def update_status(conn: sqlite3.Connection, instruction_id: str, status: str) -> bool:
    cursor = conn.execute(
        "UPDATE release_instructions SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now(), instruction_id),
    )
    return cursor.rowcount == 1
