"""`audit_events` tablosu (Plan 03 / Faz 3B, v2 §5.21).

Registry kaydı bilinçli olarak burada YAPILMAZ (bkz. `005_participants_invitations.py`
başlık notu) — Berke'nin final entegrasyon commit'i ekler. Branch testlerinde
doğrudan `apply(conn)` ile çağrılır.

`actor_user_id`/`acting_entity_id` kolonlarına FK eklenmedi (aynı gerekçe:
`users`/`legal_entities` bu migration'ın bağımlılık zincirinde değil).
`transaction_id` nullable'dır (audit event her zaman bir işleme bağlı
olmayabilir, örn. entity/kullanıcı seviyesi aksiyonlar) ve var olduğunda
`transactions(id)`'e FK'lıdır.
"""

from __future__ import annotations

import sqlite3

VERSION = "006"
NAME = "audit_events"

STATEMENTS = (
    """CREATE TABLE audit_events (
        id TEXT PRIMARY KEY,
        transaction_id TEXT,
        actor_type TEXT NOT NULL,
        actor_user_id TEXT,
        acting_entity_id TEXT,
        action TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        request_id TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY (transaction_id) REFERENCES transactions(id)
    )""",
    """CREATE INDEX idx_audit_events_transaction
        ON audit_events(transaction_id, created_at)""",
    """CREATE INDEX idx_audit_events_target
        ON audit_events(target_type, target_id)""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
