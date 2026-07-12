"""Plan 07 processing job kayıtları.

Job satırları provider side-effect'i değildir; extraction/funding/release ve
reconciliation işlerinin süreç ölümü sonrasında yeniden bulunabilmesini sağlar.
Migration additive'tir ve job servisinin reason-code/state geçişlerini
uygulama katmanına bırakır.
"""

from __future__ import annotations

import sqlite3

VERSION = "018"
NAME = "processing_jobs"

STATEMENTS = (
    """CREATE TABLE processing_jobs (
        id TEXT PRIMARY KEY,
        transaction_id TEXT,
        kind TEXT NOT NULL
            CHECK (kind IN ('extraction', 'funding', 'release', 'reconcile')),
        source_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued'
            CHECK (status IN (
                'queued', 'running', 'succeeded', 'failed', 'unknown',
                'retry_pending'
            )),
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        last_error_code TEXT,
        locked_at TEXT,
        started_at TEXT,
        finished_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(kind, idempotency_key),
        FOREIGN KEY (transaction_id) REFERENCES transactions(id)
    )""",
    """CREATE INDEX idx_processing_jobs_status_lock
        ON processing_jobs(status, locked_at)""",
    """CREATE INDEX idx_processing_jobs_transaction
        ON processing_jobs(transaction_id, kind, created_at)""",
    """CREATE INDEX idx_processing_jobs_source
        ON processing_jobs(kind, source_id, created_at)""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
