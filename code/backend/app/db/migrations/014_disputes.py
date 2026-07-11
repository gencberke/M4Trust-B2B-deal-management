"""Human-controlled dispute lifecycle (Plan 05 / Faz 5B, v2 §4.5/§5.16-5.17/§8.6).

Dispute yalnız yetkili insan eylemidir: video anomaly veya review case tek
başına dispute açamaz (bkz. `services/disputes.py`). `dispute_actions`
append-only bir zaman çizelgesidir — kim ne zaman ne yaptı sonradan
değiştirilemez.

Registry kaydı (`db/migrate.py`, `db/migrations/__init__.py`) bilinçli
olarak burada YAPILMAZ — Berke'nin Plan 05 kapanış entegrasyon commit'i
ekler. Branch testlerinde bu modül doğrudan `apply(conn)` ile çağrılır.
"""

from __future__ import annotations

import sqlite3

VERSION = "014"
NAME = "disputes"

STATEMENTS = (
    """CREATE TABLE disputes (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        milestone_id TEXT,
        opened_by_user_id TEXT NOT NULL,
        opened_by_entity_id TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        description TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open'
            CHECK (status IN (
                'open', 'awaiting_response', 'evidence_requested', 'under_review',
                'resolved', 'cancelled'
            )),
        resolution_code TEXT,
        resolved_by_user_id TEXT,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        FOREIGN KEY (transaction_id) REFERENCES transactions(id),
        FOREIGN KEY (opened_by_user_id) REFERENCES users(id),
        FOREIGN KEY (opened_by_entity_id) REFERENCES legal_entities(id),
        FOREIGN KEY (resolved_by_user_id) REFERENCES users(id)
    )""",
    """CREATE INDEX idx_disputes_transaction
        ON disputes(transaction_id, status)""",
    """CREATE INDEX idx_disputes_milestone
        ON disputes(milestone_id, status)""",
    # Bir transaction/milestone kapsamında aynı anda birden fazla AÇIK
    # (terminal olmayan) dispute açılamaz -- `open_dispute`'un idempotency'si
    # ve `has_open_dispute`'un tekil-kaynak varsayımı buna dayanır.
    """CREATE UNIQUE INDEX ux_disputes_one_open_per_scope
        ON disputes(transaction_id, COALESCE(milestone_id, ''))
        WHERE status NOT IN ('resolved', 'cancelled')""",
    """CREATE TABLE dispute_actions (
        id TEXT PRIMARY KEY,
        dispute_id TEXT NOT NULL,
        actor_user_id TEXT NOT NULL,
        acting_entity_id TEXT NOT NULL,
        action TEXT NOT NULL
            CHECK (action IN ('comment', 'attach_evidence', 'resolve', 'cancel', 'escalate_dispute')),
        evidence_id TEXT,
        payload_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (dispute_id) REFERENCES disputes(id),
        FOREIGN KEY (actor_user_id) REFERENCES users(id),
        FOREIGN KEY (acting_entity_id) REFERENCES legal_entities(id),
        FOREIGN KEY (evidence_id) REFERENCES evidence_records(id)
    )""",
    """CREATE INDEX idx_dispute_actions_dispute
        ON dispute_actions(dispute_id, created_at)""",
    # append-only: dispute_actions hiçbir koşulda update/delete edilemez --
    # "aynı transaction'a ait olmayan evidence_id" gibi kabul kuralları
    # uygulama katmanında (services/disputes.py) denetlenir; DB burada yalnız
    # geçmişin sonradan değiştirilemeyeceğini garanti eder.
    """CREATE TRIGGER trg_dispute_actions_no_update
        BEFORE UPDATE ON dispute_actions
        BEGIN
            SELECT RAISE(ABORT, 'dispute_actions is append-only: update yasak');
        END""",
    """CREATE TRIGGER trg_dispute_actions_no_delete
        BEFORE DELETE ON dispute_actions
        BEGIN
            SELECT RAISE(ABORT, 'dispute_actions is append-only: delete yasak');
        END""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
