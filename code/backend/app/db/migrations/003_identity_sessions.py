"""Kullanıcı kimliği ve oturum yönetimi tabloları (Plan 03 / Faz 3A)."""

from __future__ import annotations

import sqlite3

VERSION = "003"
NAME = "identity_sessions"

STATEMENTS = (
    """CREATE TABLE users (
        id TEXT PRIMARY KEY,
        email_normalized TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        phone_ciphertext TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        platform_role TEXT,
        email_verified_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE UNIQUE INDEX ux_users_email_normalized ON users(email_normalized)",
    """CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        token_hash TEXT NOT NULL,
        csrf_token_hash TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked_at TEXT,
        created_at TEXT NOT NULL,
        last_seen_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    "CREATE UNIQUE INDEX ux_sessions_token_hash ON sessions(token_hash)",
    "CREATE INDEX ix_sessions_user_id ON sessions(user_id)",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
