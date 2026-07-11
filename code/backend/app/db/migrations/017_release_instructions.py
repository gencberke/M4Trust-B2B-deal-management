"""Plan 06A idempotent release-instruction persistence."""

from __future__ import annotations

import sqlite3

VERSION = "017"
NAME = "release_instructions"

STATEMENTS = (
    """CREATE TABLE release_instructions (
        id TEXT PRIMARY KEY,
        funding_unit_id TEXT NOT NULL,
        provider_payment_id TEXT NOT NULL,
        operation_type TEXT NOT NULL DEFAULT 'approve_pool_payment',
        idempotency_key TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL
            CHECK (status IN ('created', 'submitted', 'confirmed', 'failed', 'unknown')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(funding_unit_id, operation_type),
        FOREIGN KEY (funding_unit_id) REFERENCES funding_units(id),
        FOREIGN KEY (provider_payment_id) REFERENCES provider_payments(id)
    )""",
    """CREATE INDEX idx_release_instructions_status
        ON release_instructions(status, updated_at)""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
