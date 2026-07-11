"""`transaction_invitations` persistence seam'i.

Raw invitation token burada asla saklanmaz/loglanmaz — yalnız `token_hash`
(SHA-256) ile lookup yapılır. Yalnız çağıranın `conn`'unu kullanır.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_invitation(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    participant_role: str,
    invited_email_normalized: str,
    token_hash: str,
    expires_at: str,
    created_by_user_id: str,
) -> sqlite3.Row:
    invitation_id = uuid4().hex
    conn.execute(
        """INSERT INTO transaction_invitations (
            id, transaction_id, participant_role, invited_email_normalized, token_hash,
            expires_at, status, created_by_user_id, accepted_by_user_id, accepted_at,
            revoked_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL, NULL, ?)""",
        (
            invitation_id,
            transaction_id,
            participant_role,
            invited_email_normalized,
            token_hash,
            expires_at,
            created_by_user_id,
            _now_iso(),
        ),
    )
    return get_invitation_by_id(conn, invitation_id)


def get_invitation_by_id(conn: sqlite3.Connection, invitation_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM transaction_invitations WHERE id = ?", (invitation_id,)
    ).fetchone()


def get_invitation_by_token_hash(conn: sqlite3.Connection, token_hash: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM transaction_invitations WHERE token_hash = ?", (token_hash,)
    ).fetchone()


def list_invitations_for_transaction(
    conn: sqlite3.Connection, transaction_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM transaction_invitations WHERE transaction_id = ? ORDER BY created_at",
        (transaction_id,),
    ).fetchall()


def try_mark_accepted(
    conn: sqlite3.Connection, invitation_id: str, *, accepted_by_user_id: str
) -> bool:
    """Yalnız hâlâ `pending` ise `accepted` yapar; concurrency-safe compare-and-swap.

    Dönen `True`/`False`, çağrının satırı gerçekten değiştirip değiştirmediğini
    söyler -- eşzamanlı iki accept'ten yalnız biri `True` alır (tek kullanımlık
    garanti, aynı işlemde ekstra kilit gerekmez)."""
    cursor = conn.execute(
        "UPDATE transaction_invitations SET status = 'accepted', accepted_by_user_id = ?, "
        "accepted_at = ? WHERE id = ? AND status = 'pending'",
        (accepted_by_user_id, _now_iso(), invitation_id),
    )
    return cursor.rowcount == 1


def mark_revoked(conn: sqlite3.Connection, invitation_id: str) -> bool:
    cursor = conn.execute(
        "UPDATE transaction_invitations SET status = 'revoked', revoked_at = ? "
        "WHERE id = ? AND status = 'pending'",
        (_now_iso(), invitation_id),
    )
    return cursor.rowcount == 1


def revoke_pending_for_role(
    conn: sqlite3.Connection,
    transaction_id: str,
    participant_role: str,
    *,
    exclude_invitation_id: str | None = None,
) -> int:
    """Aynı transaction/role için diğer canlı davetleri açıkça geçersizleştirir."""
    params: list[str] = [_now_iso(), transaction_id, participant_role]
    sql = (
        "UPDATE transaction_invitations SET status = 'revoked', revoked_at = ? "
        "WHERE transaction_id = ? AND participant_role = ? AND status = 'pending'"
    )
    if exclude_invitation_id is not None:
        sql += " AND id != ?"
        params.append(exclude_invitation_id)
    return conn.execute(sql, params).rowcount
