"""Auth throttling, lockout and single-use action tokens (Plan 09 / 9B)."""

from __future__ import annotations

import sqlite3

VERSION = "021"
NAME = "auth_verification_reset_tokens"

STATEMENTS = (
    "ALTER TABLE users ADD COLUMN failed_login_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0)",
    "ALTER TABLE users ADD COLUMN failed_login_window_started_at TEXT",
    "ALTER TABLE users ADD COLUMN locked_until TEXT",
    """CREATE TABLE auth_action_tokens (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        purpose TEXT NOT NULL CHECK (purpose IN ('password_reset', 'email_verification')),
        token_hash TEXT NOT NULL UNIQUE,
        expires_at TEXT NOT NULL,
        used_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    """CREATE INDEX idx_auth_action_tokens_user_purpose
        ON auth_action_tokens(user_id, purpose, created_at DESC)""",
    """CREATE TRIGGER trg_auth_action_tokens_bound_immutable
        BEFORE UPDATE ON auth_action_tokens
        WHEN NEW.id != OLD.id
          OR NEW.user_id != OLD.user_id
          OR NEW.purpose != OLD.purpose
          OR NEW.token_hash != OLD.token_hash
          OR NEW.expires_at != OLD.expires_at
          OR NEW.created_at != OLD.created_at
          OR (OLD.used_at IS NOT NULL AND NEW.used_at != OLD.used_at)
        BEGIN
            SELECT RAISE(ABORT, 'auth_action_tokens bound fields are immutable');
        END""",
    """CREATE TRIGGER trg_auth_action_tokens_no_delete
        BEFORE DELETE ON auth_action_tokens
        BEGIN
            SELECT RAISE(ABORT, 'auth_action_tokens delete is not allowed');
        END""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
