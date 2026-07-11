"""Legal entity ve membership tabloları (Plan 03 / Faz 3A)."""

from __future__ import annotations

import sqlite3

VERSION = "004"
NAME = "legal_entities_memberships"

STATEMENTS = (
    """CREATE TABLE legal_entities (
        id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        legal_name TEXT NOT NULL,
        tax_identifier_type TEXT NOT NULL,
        tax_identifier_ciphertext TEXT NOT NULL,
        tax_identifier_lookup_hmac TEXT NOT NULL,
        tax_identifier_last4 TEXT NOT NULL,
        tax_office TEXT,
        address_json TEXT,
        verification_status TEXT NOT NULL DEFAULT 'self_declared',
        created_by_user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (created_by_user_id) REFERENCES users(id)
    )""",
    "CREATE INDEX ix_legal_entities_tax_identifier_lookup_hmac "
    "ON legal_entities(tax_identifier_lookup_hmac)",
    """CREATE TABLE memberships (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        legal_entity_id TEXT NOT NULL,
        role TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (legal_entity_id) REFERENCES legal_entities(id) ON DELETE CASCADE
    )""",
    "CREATE UNIQUE INDEX ux_memberships_user_entity ON memberships(user_id, legal_entity_id)",
    "CREATE INDEX ix_memberships_legal_entity_id ON memberships(legal_entity_id)",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
