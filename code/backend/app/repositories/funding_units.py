"""Funding-unit persistence and status transitions for Plan 06A."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert(
    conn: sqlite3.Connection,
    *,
    unit_id: str,
    transaction_id: str,
    ratification_package_id: str,
    milestone_id: str,
    sequence: int,
    title: str,
    amount_minor: int,
    currency: str,
    eligibility_type: str,
    eligibility_payload_json: str,
    provider_profile: str,
    other_trx_code: str,
    now: str | None = None,
) -> sqlite3.Row:
    timestamp = now or _now()
    conn.execute(
        """INSERT INTO funding_units (
            id, transaction_id, ratification_package_id, milestone_id, sequence,
            title, amount_minor, currency, eligibility_type, eligibility_payload_json,
            provider_profile, other_trx_code, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?)""",
        (
            unit_id,
            transaction_id,
            ratification_package_id,
            milestone_id,
            sequence,
            title,
            amount_minor,
            currency,
            eligibility_type,
            eligibility_payload_json,
            provider_profile,
            other_trx_code,
            timestamp,
            timestamp,
        ),
    )
    return get_by_id(conn, unit_id)


def get_by_id(conn: sqlite3.Connection, unit_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM funding_units WHERE id = ?", (unit_id,)).fetchone()


def get_by_package_and_sequence(
    conn: sqlite3.Connection, *, package_id: str, sequence: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM funding_units WHERE ratification_package_id = ? AND sequence = ?",
        (package_id, sequence),
    ).fetchone()


def list_for_transaction(conn: sqlite3.Connection, transaction_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM funding_units WHERE transaction_id = ? ORDER BY sequence ASC, id ASC",
        (transaction_id,),
    ).fetchall()


def list_for_milestone(conn: sqlite3.Connection, milestone_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM funding_units WHERE milestone_id = ? ORDER BY sequence ASC, id ASC",
        (milestone_id,),
    ).fetchall()


def next_attempt_no(conn: sqlite3.Connection, *, funding_unit_id: str, operation_type: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(attempt_no), 0) FROM provider_operations "
        "WHERE funding_unit_id = ? AND operation_type = ?",
        (funding_unit_id, operation_type),
    ).fetchone()
    return int(row[0]) + 1


def update_status(conn: sqlite3.Connection, unit_id: str, status: str) -> bool:
    cursor = conn.execute(
        "UPDATE funding_units SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now(), unit_id),
    )
    return cursor.rowcount == 1


def count_by_status(conn: sqlite3.Connection, transaction_id: str, status: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM funding_units WHERE transaction_id = ? AND status = ?",
        (transaction_id, status),
    ).fetchone()
    return int(row[0])
