"""Manual review tabloları (Plan 04 / Wave A / Faz 4B, v2 §5.14-5.15).

Registry kaydı (`db/migrate.py::_MIGRATION_MODULES`,
`db/migrations/__init__.py`) bilinçli olarak burada YAPILMAZ — Berke'nin
final Wave A entegrasyon commit'i ekler (bkz. plan §4). Branch testlerinde bu
modül doğrudan `apply(conn)` ile çağrılır.

`assigned_to_user_id`/`opened_by_user_id`/`resolved_by_user_id`/
`actor_user_id` kolonlarına kasıtlı olarak FOREIGN KEY eklenmedi: bu alanlar
`users` tablosuna (3A) işaret eder ama bu migration'ın kendi bağımlılık
zincirinde değildir; branch testlerinde 3A'nın gerçek şeması zaten mevcut
olduğu için (integration HEAD'den açıldı) sorun çıkarmaz, ama kontrat bunu
zorunlu kılmaz.
"""

from __future__ import annotations

import sqlite3

VERSION = "010"
NAME = "review_cases"

STATEMENTS = (
    """CREATE TABLE review_cases (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        phase TEXT NOT NULL
            CHECK (phase IN ('pre_ratification', 'settlement', 'payment')),
        source_type TEXT NOT NULL
            CHECK (source_type IN ('validator', 'party_mismatch', 'evidence', 'video', 'payment', 'system')),
        source_id TEXT,
        reason_code TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('warning', 'blocking')),
        status TEXT NOT NULL DEFAULT 'open'
            CHECK (status IN ('open', 'evidence_requested', 'resolved', 'escalated', 'cancelled')),
        assigned_to_user_id TEXT,
        opened_by_actor_type TEXT NOT NULL,
        opened_by_user_id TEXT,
        resolved_by_user_id TEXT,
        resolution_code TEXT,
        resolution_note TEXT,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        FOREIGN KEY (transaction_id) REFERENCES transactions(id)
    )""",
    """CREATE INDEX idx_review_cases_transaction_status
        ON review_cases(transaction_id, status)""",
    """CREATE INDEX idx_review_cases_source
        ON review_cases(transaction_id, source_type, source_id)""",
    """CREATE INDEX idx_review_cases_assigned
        ON review_cases(assigned_to_user_id, status)""",
    # Aynı (transaction, phase, source_type, source_id, reason_code) için
    # aktif (open/evidence_requested/escalated) bir BLOCKING case'ten fazlası
    # DB seviyesinde reddedilir -- `open_case`'in idempotency'si bu constraint'e
    # dayanır (uygulama katmanındaki önceden-kontrol yarış durumunda yetersiz
    # kalabilir, source of truth burasıdır).
    """CREATE UNIQUE INDEX ux_review_cases_active_blocking_source
        ON review_cases(transaction_id, phase, source_type, COALESCE(source_id, ''), reason_code)
        WHERE severity = 'blocking' AND status IN ('open', 'evidence_requested', 'escalated')""",
    """CREATE TABLE review_actions (
        id TEXT PRIMARY KEY,
        review_case_id TEXT NOT NULL,
        actor_user_id TEXT NOT NULL,
        acting_entity_id TEXT,
        action TEXT NOT NULL
            CHECK (action IN ('comment', 'request_evidence', 'resolve_continue', 'resolve_reject', 'escalate', 'cancel')),
        payload_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (review_case_id) REFERENCES review_cases(id)
    )""",
    """CREATE INDEX idx_review_actions_case
        ON review_actions(review_case_id, created_at)""",
    # append-only: review_actions hiçbir koşulda update/delete edilemez --
    # denetim izinin (kim ne zaman ne dedi) sonradan değiştirilemez olması
    # gerekir.
    """CREATE TRIGGER trg_review_actions_no_update
        BEFORE UPDATE ON review_actions
        BEGIN
            SELECT RAISE(ABORT, 'review_actions is append-only: update yasak');
        END""",
    """CREATE TRIGGER trg_review_actions_no_delete
        BEFORE DELETE ON review_actions
        BEGIN
            SELECT RAISE(ABORT, 'review_actions is append-only: delete yasak');
        END""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
