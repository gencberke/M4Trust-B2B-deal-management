"""Canonical ratification package persistence (Plan 04 / Wave B / Faz 4D).

Package payload'ı ve ona bağlı hash alanları immutable'dır. Yalnız status ile
durum zaman damgaları servis üzerinden kontrollü biçimde değişebilir; package
silinemez. Migration additive, sıralı ve atomiktir.
"""

from __future__ import annotations

import sqlite3

VERSION = "011"
NAME = "ratification_packages"

STATEMENTS = (
    """CREATE TABLE ratification_packages (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        document_id TEXT NOT NULL,
        rule_set_version_id TEXT NOT NULL,
        tracking_policy_version_id TEXT,
        canonical_payload_json TEXT NOT NULL,
        document_hash TEXT NOT NULL,
        rule_set_hash TEXT NOT NULL,
        participant_snapshot_hash TEXT NOT NULL,
        tracking_policy_hash TEXT NOT NULL,
        package_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft'
            CHECK (status IN ('draft', 'open', 'complete', 'superseded', 'cancelled')),
        created_at TEXT NOT NULL,
        opened_at TEXT,
        completed_at TEXT,
        UNIQUE(transaction_id, version),
        FOREIGN KEY (transaction_id) REFERENCES transactions(id),
        FOREIGN KEY (document_id) REFERENCES contract_documents(id),
        FOREIGN KEY (rule_set_version_id) REFERENCES rule_set_versions(id)
    )""",
    """CREATE INDEX idx_ratification_packages_current
        ON ratification_packages(transaction_id, status, version)""",
    """CREATE INDEX idx_ratification_packages_rule_version
        ON ratification_packages(rule_set_version_id)""",
    """CREATE TRIGGER trg_ratification_packages_bound_inputs_immutable
        BEFORE UPDATE ON ratification_packages
        WHEN NEW.id != OLD.id
          OR NEW.transaction_id != OLD.transaction_id
          OR NEW.version != OLD.version
          OR NEW.document_id != OLD.document_id
          OR NEW.rule_set_version_id != OLD.rule_set_version_id
          OR COALESCE(NEW.tracking_policy_version_id, '')
             != COALESCE(OLD.tracking_policy_version_id, '')
          OR NEW.canonical_payload_json != OLD.canonical_payload_json
          OR NEW.document_hash != OLD.document_hash
          OR NEW.rule_set_hash != OLD.rule_set_hash
          OR NEW.participant_snapshot_hash != OLD.participant_snapshot_hash
          OR NEW.tracking_policy_hash != OLD.tracking_policy_hash
          OR NEW.package_hash != OLD.package_hash
          OR NEW.created_at != OLD.created_at
        BEGIN
            SELECT RAISE(ABORT, 'ratification_packages bound inputs are immutable');
        END""",
    """CREATE TRIGGER trg_ratification_packages_no_delete
        BEFORE DELETE ON ratification_packages
        BEGIN
            SELECT RAISE(ABORT, 'ratification_packages delete yasak');
        END""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
