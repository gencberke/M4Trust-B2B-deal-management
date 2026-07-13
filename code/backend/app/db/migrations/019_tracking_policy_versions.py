"""Additive tracking-policy history (Plan 09 / Faz 9A).

The mutable ``tracking_policies`` table remains the compatibility/current
view. Each materially different snapshot is appended to this immutable
history and canonical ratification packages bind its id.
"""

from __future__ import annotations

import sqlite3

VERSION = "019"
NAME = "tracking_policy_versions"

STATEMENTS = (
    """CREATE TABLE tracking_policy_versions (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK (version > 0),
        recommendation TEXT,
        recommendation_reason_codes_json TEXT NOT NULL DEFAULT '[]',
        physical_delivery_confirmed INTEGER,
        tracking_mode TEXT NOT NULL
            CHECK (tracking_mode IN ('off', 'document_only', 'document_and_video')),
        video_role TEXT NOT NULL CHECK (video_role = 'advisory'),
        status TEXT NOT NULL CHECK (status IN ('draft', 'locked')),
        snapshot_json TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL,
        configured_by_user_id TEXT,
        locked_by_user_id TEXT,
        configured_at TEXT,
        locked_at TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(transaction_id, version),
        UNIQUE(transaction_id, snapshot_hash),
        FOREIGN KEY (transaction_id) REFERENCES transactions(id),
        FOREIGN KEY (configured_by_user_id) REFERENCES users(id),
        FOREIGN KEY (locked_by_user_id) REFERENCES users(id)
    )""",
    """CREATE INDEX idx_tracking_policy_versions_current
        ON tracking_policy_versions(transaction_id, version DESC)""",
    """CREATE TRIGGER trg_tracking_policy_versions_no_update
        BEFORE UPDATE ON tracking_policy_versions
        BEGIN
            SELECT RAISE(ABORT, 'tracking_policy_versions is immutable');
        END""",
    """CREATE TRIGGER trg_tracking_policy_versions_no_delete
        BEFORE DELETE ON tracking_policy_versions
        BEGIN
            SELECT RAISE(ABORT, 'tracking_policy_versions is immutable');
        END""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
