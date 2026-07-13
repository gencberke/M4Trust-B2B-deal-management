"""Add encrypted markdown references and retention tombstones (Plan 09)."""

from __future__ import annotations

import sqlite3

VERSION = "020"
NAME = "document_storage_references"

STATEMENTS = (
    "ALTER TABLE transactions ADD COLUMN markdown_storage_ref TEXT",
    "ALTER TABLE transactions ADD COLUMN masked_markdown_storage_ref TEXT",
    "ALTER TABLE transactions ADD COLUMN markdown_deleted_at TEXT",
    "ALTER TABLE contract_documents ADD COLUMN retention_deleted_at TEXT",
    "ALTER TABLE evidence_records ADD COLUMN retention_deleted_at TEXT",
    """CREATE UNIQUE INDEX idx_transactions_markdown_storage_ref
        ON transactions(markdown_storage_ref)
        WHERE markdown_storage_ref IS NOT NULL""",
    """CREATE UNIQUE INDEX idx_transactions_masked_markdown_storage_ref
        ON transactions(masked_markdown_storage_ref)
        WHERE masked_markdown_storage_ref IS NOT NULL""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
