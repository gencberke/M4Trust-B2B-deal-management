"""User ve session satır/sorgu erişimi (Faz 3A)."""

from __future__ import annotations

from sqlite3 import Connection, Row
from uuid import uuid4


def insert_user(
    conn: Connection,
    *,
    email_normalized: str,
    password_hash: str,
    first_name: str,
    last_name: str,
    now: str,
) -> str:
    user_id = uuid4().hex
    conn.execute(
        """INSERT INTO users
        (id, email_normalized, password_hash, first_name, last_name,
         status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
        (user_id, email_normalized, password_hash, first_name, last_name, now, now),
    )
    return user_id


def get_user_by_email(conn: Connection, email_normalized: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM users WHERE email_normalized = ?", (email_normalized,)
    ).fetchone()


def get_user_by_id(conn: Connection, user_id: str) -> Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def insert_session(
    conn: Connection,
    *,
    user_id: str,
    token_hash: str,
    csrf_token_hash: str,
    expires_at: str,
    now: str,
) -> str:
    session_id = uuid4().hex
    conn.execute(
        """INSERT INTO sessions
        (id, user_id, token_hash, csrf_token_hash, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, user_id, token_hash, csrf_token_hash, expires_at, now),
    )
    return session_id


def get_session_by_token_hash(conn: Connection, token_hash: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)
    ).fetchone()


def revoke_session(conn: Connection, *, session_id: str, now: str) -> None:
    conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
        (now, session_id),
    )


def revoke_all_sessions_for_user(conn: Connection, *, user_id: str, now: str) -> int:
    cursor = conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (now, user_id),
    )
    return cursor.rowcount


def touch_last_seen(conn: Connection, *, session_id: str, now: str) -> None:
    conn.execute(
        "UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now, session_id)
    )
