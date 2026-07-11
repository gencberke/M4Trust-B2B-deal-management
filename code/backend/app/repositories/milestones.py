"""Milestone persistence seam for Plan 06A."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert(
    conn: sqlite3.Connection,
    *,
    milestone_id: str,
    transaction_id: str,
    ratification_package_id: str,
    rule_set_version_id: str,
    rule_index: int,
    title: str,
    trigger_type: str,
    percentage_basis_points: int,
    amount_minor: int,
    currency: str,
    required_evidence_json: str,
    release_mode: str,
    now: str | None = None,
) -> sqlite3.Row:
    timestamp = now or _now()
    conn.execute(
        """INSERT INTO milestones (
            id, transaction_id, ratification_package_id, rule_set_version_id,
            rule_index, title, trigger_type, percentage_basis_points, amount_minor,
            currency, required_evidence_json, release_mode, status,
            released_amount_minor, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)""",
        (
            milestone_id,
            transaction_id,
            ratification_package_id,
            rule_set_version_id,
            rule_index,
            title,
            trigger_type,
            percentage_basis_points,
            amount_minor,
            currency,
            required_evidence_json,
            release_mode,
            timestamp,
            timestamp,
        ),
    )
    return get_by_id(conn, milestone_id)


def new_id() -> str:
    return uuid4().hex


def get_by_id(conn: sqlite3.Connection, milestone_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM milestones WHERE id = ?", (milestone_id,)).fetchone()


def list_for_transaction(conn: sqlite3.Connection, transaction_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM milestones WHERE transaction_id = ? ORDER BY rule_index ASC, id ASC",
        (transaction_id,),
    ).fetchall()


def list_for_package(
    conn: sqlite3.Connection, ratification_package_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM milestones WHERE ratification_package_id = ? ORDER BY rule_index ASC, id ASC",
        (ratification_package_id,),
    ).fetchall()


def update_status(conn: sqlite3.Connection, milestone_id: str, status: str) -> bool:
    cursor = conn.execute(
        "UPDATE milestones SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now(), milestone_id),
    )
    return cursor.rowcount == 1


def update_released_amount(
    conn: sqlite3.Connection, milestone_id: str, *, released_amount_minor: int, status: str
) -> bool:
    cursor = conn.execute(
        "UPDATE milestones SET released_amount_minor = ?, status = ?, updated_at = ? "
        "WHERE id = ?",
        (released_amount_minor, status, _now(), milestone_id),
    )
    return cursor.rowcount == 1
