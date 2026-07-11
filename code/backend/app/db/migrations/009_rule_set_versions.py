"""`rule_set_versions` (Plan 04 / Faz 4A, v2 §5.10) — immutable kural sürümleri.

`rules_json` mevcut `ExtractionJSON` ile birebir doğrulanabilir kanonik payload'dır
(şema genişletilmez); `rules_hash` bu kanonik string'in UTF-8 byte'larından
SHA-256 ile hesaplanır (bkz. `services/rule_versions.py::_canonical_json`).
Revizyon her zaman yeni bir satır üretir — eski satırın içerik alanları
(`rules_json`/`rules_hash`/`transaction_id`/`version`) hiçbir zaman UPDATE
edilmez; yalnızca `status`/`validator_status`/`validator_report_json` alanları
sonradan güncellenebilir (`validate_version`/`supersede`). Bu ayrım DB
seviyesinde bir trigger ile fail-closed uygulanır: içerik alanlarından biri
değişirse UPDATE reddedilir.
"""

from __future__ import annotations

import sqlite3

VERSION = "009"
NAME = "rule_set_versions"

STATEMENTS = (
    """CREATE TABLE rule_set_versions (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        parent_version_id TEXT,
        source_extraction_run_id TEXT,
        rules_json TEXT NOT NULL,
        rules_hash TEXT NOT NULL,
        validator_status TEXT,
        validator_report_json TEXT,
        status TEXT NOT NULL DEFAULT 'draft',
        created_by_user_id TEXT,
        created_by_actor_type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(transaction_id, version),
        FOREIGN KEY (transaction_id) REFERENCES transactions(id),
        FOREIGN KEY (parent_version_id) REFERENCES rule_set_versions(id),
        FOREIGN KEY (source_extraction_run_id) REFERENCES extraction_runs(id)
    )""",
    """CREATE INDEX idx_rule_set_versions_current
        ON rule_set_versions(transaction_id, status)""",
    """CREATE TRIGGER trg_rule_set_versions_content_immutable
        BEFORE UPDATE ON rule_set_versions
        WHEN NEW.rules_json != OLD.rules_json
          OR NEW.rules_hash != OLD.rules_hash
          OR NEW.transaction_id != OLD.transaction_id
          OR NEW.version != OLD.version
        BEGIN
            SELECT RAISE(ABORT, 'rule_set_versions content fields are immutable');
        END""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
