"""`transactions`'a hesap sahipliği kolonları (Plan 03 / Faz 3C, v2 §2.8/§5.6).

Additive: mevcut satırlar `lifecycle_version='legacy_v1'` olarak backfill edilir
(SQLite `ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT` otomatik doldurur).
Yeni authenticated create akışı `account_v2` yazar; legacy anonim akış
değişmeden `legacy_v1` üretmeye devam eder — bkz. `routers/transactions.py`.
"""

from __future__ import annotations

import sqlite3

VERSION = "007"
NAME = "transaction_lifecycle_v2"

STATEMENTS = (
    "ALTER TABLE transactions ADD COLUMN created_by_user_id TEXT",
    "ALTER TABLE transactions ADD COLUMN owner_entity_id TEXT",
    "ALTER TABLE transactions ADD COLUMN lifecycle_version TEXT NOT NULL DEFAULT 'legacy_v1'",
    "ALTER TABLE transactions ADD COLUMN content_sha256 TEXT",
    "CREATE INDEX ix_transactions_created_by_user_id ON transactions(created_by_user_id)",
    "CREATE INDEX ix_transactions_owner_entity_id ON transactions(owner_entity_id)",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
