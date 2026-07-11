"""`transaction_participants` + `transaction_assignments` persistence seam'i.

Saf SQL — Pydantic dönüşümü `services/participants.py`'de yapılır. Yalnız
çağıranın `conn`'unu kullanır, kendi commit/rollback yapmaz.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_participant(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    role: str,
    legal_entity_id: str | None,
    status: str,
    extracted_snapshot: dict[str, Any] | None = None,
) -> sqlite3.Row:
    participant_id = uuid4().hex
    now = _now_iso()
    conn.execute(
        """INSERT INTO transaction_participants (
            id, transaction_id, role, legal_entity_id, status,
            extracted_snapshot_json, declared_snapshot_json, confirmed_snapshot_json,
            confirmed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)""",
        (
            participant_id,
            transaction_id,
            role,
            legal_entity_id,
            status,
            json.dumps(extracted_snapshot) if extracted_snapshot is not None else None,
            now,
            now,
        ),
    )
    return get_participant_by_id(conn, participant_id)


def get_participant_by_id(conn: sqlite3.Connection, participant_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM transaction_participants WHERE id = ?", (participant_id,)
    ).fetchone()


def get_participant(
    conn: sqlite3.Connection, transaction_id: str, role: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM transaction_participants WHERE transaction_id = ? AND role = ?",
        (transaction_id, role),
    ).fetchone()


def list_participants(conn: sqlite3.Connection, transaction_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM transaction_participants WHERE transaction_id = ? ORDER BY role",
        (transaction_id,),
    ).fetchall()


def link_participant_to_entity(
    conn: sqlite3.Connection, participant_id: str, *, legal_entity_id: str, status: str
) -> sqlite3.Row:
    conn.execute(
        "UPDATE transaction_participants SET legal_entity_id = ?, status = ?, updated_at = ? "
        "WHERE id = ?",
        (legal_entity_id, status, _now_iso(), participant_id),
    )
    return get_participant_by_id(conn, participant_id)


def update_declared_snapshot(
    conn: sqlite3.Connection, participant_id: str, *, declared_snapshot: dict[str, Any], status: str
) -> sqlite3.Row:
    conn.execute(
        "UPDATE transaction_participants SET declared_snapshot_json = ?, status = ?, updated_at = ? "
        "WHERE id = ?",
        (json.dumps(declared_snapshot), status, _now_iso(), participant_id),
    )
    return get_participant_by_id(conn, participant_id)


def confirm_participant(
    conn: sqlite3.Connection, participant_id: str, *, confirmed_snapshot: dict[str, Any]
) -> sqlite3.Row:
    now = _now_iso()
    conn.execute(
        "UPDATE transaction_participants SET confirmed_snapshot_json = ?, confirmed_at = ?, "
        "status = 'confirmed', updated_at = ? WHERE id = ?",
        (json.dumps(confirmed_snapshot), now, now, participant_id),
    )
    return get_participant_by_id(conn, participant_id)


# --- transaction_assignments -------------------------------------------------


def create_assignment(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    participant_id: str | None,
    user_id: str,
    legal_entity_id: str,
    role: str,
    status: str = "active",
) -> sqlite3.Row:
    assignment_id = uuid4().hex
    conn.execute(
        """INSERT INTO transaction_assignments (
            id, transaction_id, participant_id, user_id, legal_entity_id, role, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            assignment_id,
            transaction_id,
            participant_id,
            user_id,
            legal_entity_id,
            role,
            status,
            _now_iso(),
        ),
    )
    return conn.execute(
        "SELECT * FROM transaction_assignments WHERE id = ?", (assignment_id,)
    ).fetchone()


def get_active_assignment(
    conn: sqlite3.Connection, transaction_id: str, user_id: str, *, role: str | None = None
) -> sqlite3.Row | None:
    if role is None:
        return conn.execute(
            "SELECT * FROM transaction_assignments WHERE transaction_id = ? AND user_id = ? "
            "AND status = 'active'",
            (transaction_id, user_id),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM transaction_assignments WHERE transaction_id = ? AND user_id = ? "
        "AND status = 'active' AND role = ?",
        (transaction_id, user_id, role),
    ).fetchone()


def list_assignments(conn: sqlite3.Connection, transaction_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM transaction_assignments WHERE transaction_id = ?", (transaction_id,)
    ).fetchall()


# --- 3A tablolarına dar, salt-okunur SQL yardımcıları -------------------------
#
# `users`/`memberships` migration 003/004 (Berke, 3A) sahipliğindedir; burada
# yalnız v2 §5.1/§5.4 dondurulmuş kolon sözleşmesine göre salt-okunur sorgu
# yapılır. Berke'nin repository/service iç yapısı import EDİLMEZ.


def get_user_email_normalized(conn: sqlite3.Connection, user_id: str) -> str | None:
    row = conn.execute("SELECT email_normalized FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["email_normalized"] if row is not None else None


def has_active_membership(conn: sqlite3.Connection, user_id: str, legal_entity_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM memberships WHERE user_id = ? AND legal_entity_id = ? AND status = 'active'",
        (user_id, legal_entity_id),
    ).fetchone()
    return row is not None
