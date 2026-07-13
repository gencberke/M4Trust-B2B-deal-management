"""Hashed password-reset/email-verification token persistence."""

from __future__ import annotations

from sqlite3 import Connection, Row
from uuid import uuid4


def invalidate_unused(
    conn: Connection, *, user_id: str, purpose: str, now: str
) -> None:
    conn.execute(
        "UPDATE auth_action_tokens SET used_at = ? "
        "WHERE user_id = ? AND purpose = ? AND used_at IS NULL",
        (now, user_id, purpose),
    )


def insert(
    conn: Connection,
    *,
    user_id: str,
    purpose: str,
    token_hash: str,
    expires_at: str,
    now: str,
) -> str:
    token_id = uuid4().hex
    conn.execute(
        "INSERT INTO auth_action_tokens "
        "(id,user_id,purpose,token_hash,expires_at,created_at) VALUES (?,?,?,?,?,?)",
        (token_id, user_id, purpose, token_hash, expires_at, now),
    )
    return token_id


def get_by_hash(conn: Connection, *, token_hash: str, purpose: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM auth_action_tokens WHERE token_hash = ? AND purpose = ?",
        (token_hash, purpose),
    ).fetchone()


def consume_if_unused(conn: Connection, *, token_id: str, now: str) -> bool:
    cursor = conn.execute(
        "UPDATE auth_action_tokens SET used_at = ? WHERE id = ? AND used_at IS NULL",
        (now, token_id),
    )
    return cursor.rowcount == 1
