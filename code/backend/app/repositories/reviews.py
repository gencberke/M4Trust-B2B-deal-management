"""`review_cases` + `review_actions` persistence seam'i.

Saf SQL — yalnız çağıranın `conn`'unu kullanır, kendi commit/rollback/connect
yapmaz. `review_actions` append-only'dir (migration 010'daki trigger'lar
update/delete'i DB seviyesinde reddeder); bu modül zaten yalnız INSERT/SELECT
sağlar. Duplicate-active-blocking-case koruması migration'daki partial UNIQUE
index'tir — bu modüldeki `find_active_case` yalnız uygulama-seviyesi bir
ön-kontrol/idempotency kısayoludur, source of truth DB constraint'idir.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_case(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    phase: str,
    source_type: str,
    source_id: str | None,
    reason_code: str,
    title: str,
    description: str,
    severity: str,
    opened_by_actor_type: str,
    opened_by_user_id: str | None,
) -> sqlite3.Row:
    case_id = uuid4().hex
    conn.execute(
        """INSERT INTO review_cases (
            id, transaction_id, phase, source_type, source_id, reason_code, title,
            description, severity, status, assigned_to_user_id, opened_by_actor_type,
            opened_by_user_id, resolved_by_user_id, resolution_code, resolution_note,
            created_at, resolved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', NULL, ?, ?, NULL, NULL, NULL, ?, NULL)""",
        (
            case_id,
            transaction_id,
            phase,
            source_type,
            source_id,
            reason_code,
            title,
            description,
            severity,
            opened_by_actor_type,
            opened_by_user_id,
            _now_iso(),
        ),
    )
    return get_case_by_id(conn, case_id)


def get_case_by_id(conn: sqlite3.Connection, case_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM review_cases WHERE id = ?", (case_id,)).fetchone()


def find_active_case(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    phase: str,
    source_type: str,
    source_id: str | None,
    reason_code: str,
) -> sqlite3.Row | None:
    """Uygulama-seviyesi idempotency ön-kontrolü (DB partial UNIQUE index source of truth'tur)."""
    return conn.execute(
        """SELECT * FROM review_cases
        WHERE transaction_id = ? AND phase = ? AND source_type = ?
          AND COALESCE(source_id, '') = COALESCE(?, '') AND reason_code = ?
          AND severity = 'blocking' AND status IN ('open', 'evidence_requested', 'escalated')""",
        (transaction_id, phase, source_type, source_id, reason_code),
    ).fetchone()


def list_cases_for_transaction(conn: sqlite3.Connection, transaction_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM review_cases WHERE transaction_id = ? ORDER BY created_at", (transaction_id,)
    ).fetchall()


def has_blocking_case(
    conn: sqlite3.Connection, transaction_id: str, *, phase: str | None = None
) -> bool:
    if phase is None:
        row = conn.execute(
            "SELECT 1 FROM review_cases WHERE transaction_id = ? AND severity = 'blocking' "
            "AND status IN ('open', 'evidence_requested', 'escalated') LIMIT 1",
            (transaction_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM review_cases WHERE transaction_id = ? AND phase = ? "
            "AND severity = 'blocking' AND status IN ('open', 'evidence_requested', 'escalated') LIMIT 1",
            (transaction_id, phase),
        ).fetchone()
    return row is not None


def conditional_update_status(
    conn: sqlite3.Connection,
    case_id: str,
    *,
    expected_statuses: tuple[str, ...],
    new_status: str,
    resolved: bool = False,
    resolved_by_user_id: str | None = None,
    resolution_code: str | None = None,
    resolution_note: str | None = None,
) -> bool:
    """Yalnız case hâlâ `expected_statuses`'tan biriyse günceller (conditional/optimistic).

    Kapalı bir case'e (beklenen durumda değilse) yazılmaz -- dönen `False`,
    çağıranın "closed case'e state-changing action reddi" kuralını
    uygulaması için kullanılır.
    """
    placeholders = ",".join("?" for _ in expected_statuses)
    if resolved:
        cursor = conn.execute(
            f"""UPDATE review_cases SET status = ?, resolved_by_user_id = ?,
                resolution_code = ?, resolution_note = ?, resolved_at = ?
                WHERE id = ? AND status IN ({placeholders})""",
            (
                new_status,
                resolved_by_user_id,
                resolution_code,
                resolution_note,
                _now_iso(),
                case_id,
                *expected_statuses,
            ),
        )
    else:
        cursor = conn.execute(
            f"""UPDATE review_cases SET status = ? WHERE id = ? AND status IN ({placeholders})""",
            (new_status, case_id, *expected_statuses),
        )
    return cursor.rowcount == 1


def append_action(
    conn: sqlite3.Connection,
    *,
    review_case_id: str,
    actor_user_id: str,
    acting_entity_id: str | None,
    action: str,
    payload_json: str | None,
) -> sqlite3.Row:
    action_id = uuid4().hex
    conn.execute(
        """INSERT INTO review_actions (
            id, review_case_id, actor_user_id, acting_entity_id, action, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (action_id, review_case_id, actor_user_id, acting_entity_id, action, payload_json, _now_iso()),
    )
    return conn.execute("SELECT * FROM review_actions WHERE id = ?", (action_id,)).fetchone()


def list_actions_for_case(conn: sqlite3.Connection, review_case_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM review_actions WHERE review_case_id = ? ORDER BY created_at",
        (review_case_id,),
    ).fetchall()
