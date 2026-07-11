"""Authorized evidence ingestion (Plan 05 / Faz 5A, v2 §4.5/§5.16-5.17/§8.6).

Account işlemlerde teslimat kanıtını event payload'ı olmaktan çıkarıp
first-class, actor/entity/hash bağlı bir kayda dönüştürür. `payload_json`
dar ve tipli bir yapı taşır (ör. e-irsaliye: `{delivered_quantity}`, video:
`{counts, unit_count, damage_signals, confidence}`); ham dosya/token/PII
bu tabloya girmez (video ham byte'ları `DocumentStorageProvider`'da, yalnız
`storage_ref`+`file_sha256` burada tutulur).

Registry kaydı (`db/migrate.py`, `db/migrations/__init__.py`) bilinçli
olarak burada YAPILMAZ — Berke'nin Plan 05 kapanış entegrasyon commit'i
ekler. Branch testlerinde bu modül doğrudan `apply(conn)` ile çağrılır.
"""

from __future__ import annotations

import sqlite3

VERSION = "013"
NAME = "evidence_records"

STATEMENTS = (
    """CREATE TABLE evidence_records (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        milestone_id TEXT,
        evidence_type TEXT NOT NULL
            CHECK (evidence_type IN ('contract', 'e_irsaliye', 'video', 'e_invoice', 'other')),
        source TEXT NOT NULL
            CHECK (source IN ('upload', 'external_api', 'analyzer', 'system')),
        submitted_by_user_id TEXT NOT NULL,
        submitted_by_entity_id TEXT NOT NULL,
        external_reference TEXT,
        storage_ref TEXT,
        file_sha256 TEXT,
        payload_json TEXT NOT NULL,
        verification_status TEXT NOT NULL DEFAULT 'received'
            CHECK (verification_status IN ('received', 'verified', 'rejected', 'review_required')),
        analyzer_provider TEXT,
        analyzer_version TEXT,
        created_at TEXT NOT NULL,
        verified_at TEXT,
        UNIQUE(transaction_id, evidence_type, external_reference),
        UNIQUE(transaction_id, file_sha256),
        FOREIGN KEY (transaction_id) REFERENCES transactions(id),
        FOREIGN KEY (submitted_by_user_id) REFERENCES users(id),
        FOREIGN KEY (submitted_by_entity_id) REFERENCES legal_entities(id)
    )""",
    """CREATE INDEX idx_evidence_records_transaction
        ON evidence_records(transaction_id, evidence_type, created_at)""",
    """CREATE INDEX idx_evidence_records_milestone
        ON evidence_records(milestone_id)""",
    """CREATE INDEX idx_evidence_records_submitter
        ON evidence_records(submitted_by_user_id)""",
    # Kanıt kaydı: bağlı içerik (actor/entity/hash/payload/tip) sonradan
    # değiştirilemez. Yalnız `verification_status`/`verified_at`
    # (`repositories/evidence.py::mark_verified`) güncellenebilir; bu
    # trigger diğer tüm kolonların sabit kaldığını garanti eder.
    """CREATE TRIGGER trg_evidence_records_bound_fields_immutable
        BEFORE UPDATE ON evidence_records
        WHEN NEW.id != OLD.id
          OR NEW.transaction_id != OLD.transaction_id
          OR COALESCE(NEW.milestone_id, '') != COALESCE(OLD.milestone_id, '')
          OR NEW.evidence_type != OLD.evidence_type
          OR NEW.source != OLD.source
          OR NEW.submitted_by_user_id != OLD.submitted_by_user_id
          OR NEW.submitted_by_entity_id != OLD.submitted_by_entity_id
          OR COALESCE(NEW.external_reference, '') != COALESCE(OLD.external_reference, '')
          OR COALESCE(NEW.storage_ref, '') != COALESCE(OLD.storage_ref, '')
          OR COALESCE(NEW.file_sha256, '') != COALESCE(OLD.file_sha256, '')
          OR NEW.payload_json != OLD.payload_json
          OR NEW.created_at != OLD.created_at
        BEGIN
            SELECT RAISE(ABORT, 'evidence_records bound fields are immutable');
        END""",
    """CREATE TRIGGER trg_evidence_records_no_delete
        BEFORE DELETE ON evidence_records
        BEGIN
            SELECT RAISE(ABORT, 'evidence_records delete yasak');
        END""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
