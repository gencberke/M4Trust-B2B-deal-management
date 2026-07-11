"""Participant/assignment/invitation tabloları (Plan 03 / Faz 3B, v2 §5.5-§5.7).

Registry kaydı (`db/migrate.py::_MIGRATION_MODULES`,
`db/migrations/__init__.py`) bilinçli olarak burada YAPILMAZ — Berke'nin
final entegrasyon commit'i, 3A'nın `003`/`004`'ü ile birlikte sıralı ekler.
Bu yüzden bu modül branch testlerinde yalnız doğrudan `apply(conn)` ile
çağrılır (registry'ye bağlı değildir).

`user_id`/`legal_entity_id`/`created_by_user_id`/`accepted_by_user_id`
kolonlarına kasıtlı olarak FOREIGN KEY eklenmedi: `users`/`legal_entities`
(003/004) bu migration'ın bağımlılık zincirinde değildir ve ayrı bir
branch'te (3A) gelişiyor — var olmayan bir tabloya FK, `PRAGMA
foreign_keys=ON` altında bu branch'in izole testlerinde INSERT'i kırar.
Yalnız bu migration setinin kendi içindeki (`transactions`, kendi ürettiği
`transaction_participants`) referanslar FK'lıdır.
"""

from __future__ import annotations

import sqlite3

VERSION = "005"
NAME = "participants_invitations"

STATEMENTS = (
    """CREATE TABLE transaction_participants (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        role TEXT NOT NULL,
        legal_entity_id TEXT,
        status TEXT NOT NULL DEFAULT 'invited',
        extracted_snapshot_json TEXT,
        declared_snapshot_json TEXT,
        confirmed_snapshot_json TEXT,
        confirmed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(transaction_id, role),
        FOREIGN KEY (transaction_id) REFERENCES transactions(id)
    )""",
    """CREATE TABLE transaction_assignments (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        participant_id TEXT,
        user_id TEXT NOT NULL,
        legal_entity_id TEXT NOT NULL,
        role TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        FOREIGN KEY (transaction_id) REFERENCES transactions(id),
        FOREIGN KEY (participant_id) REFERENCES transaction_participants(id)
    )""",
    """CREATE INDEX idx_transaction_assignments_access
        ON transaction_assignments(transaction_id, user_id, status)""",
    """CREATE INDEX idx_transaction_assignments_user
        ON transaction_assignments(user_id, status)""",
    """CREATE TABLE transaction_invitations (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        participant_role TEXT NOT NULL,
        invited_email_normalized TEXT NOT NULL,
        token_hash TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_by_user_id TEXT NOT NULL,
        accepted_by_user_id TEXT,
        accepted_at TEXT,
        revoked_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (transaction_id) REFERENCES transactions(id)
    )""",
    """CREATE UNIQUE INDEX idx_transaction_invitations_token_hash
        ON transaction_invitations(token_hash)""",
    """CREATE INDEX idx_transaction_invitations_transaction
        ON transaction_invitations(transaction_id, status)""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
