"""Plan 05 corrective constraints.

013 ve 010 merge edildikten sonra iki provenance/state sözleşmesi düzeltildi:

* evidence analyzer provider/version alanları da bound-field immutable'dır.
* review action'larına insan kontrollü ``escalate_dispute`` eklendi.

Eski migration dosyaları geriye dönük değiştirilmez; bu migration mevcut
trigger/table constraint'lerini additive bir corrective step olarak yeniler.
"""

from __future__ import annotations

import sqlite3

VERSION = "023"
NAME = "plan05_remediation_constraints"

STATEMENTS = (
    "DROP TRIGGER IF EXISTS trg_evidence_records_bound_fields_immutable",
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
          OR COALESCE(NEW.analyzer_provider, '') != COALESCE(OLD.analyzer_provider, '')
          OR COALESCE(NEW.analyzer_version, '') != COALESCE(OLD.analyzer_version, '')
          OR NEW.created_at != OLD.created_at
        BEGIN
            SELECT RAISE(ABORT, 'evidence_records bound fields are immutable');
        END""",
    "DROP TRIGGER IF EXISTS trg_review_actions_no_update",
    "DROP TRIGGER IF EXISTS trg_review_actions_no_delete",
    "DROP INDEX IF EXISTS idx_review_actions_case",
    "ALTER TABLE review_actions RENAME TO review_actions_before_plan05_remediation",
    """CREATE TABLE review_actions (
        id TEXT PRIMARY KEY,
        review_case_id TEXT NOT NULL,
        actor_user_id TEXT NOT NULL,
        acting_entity_id TEXT,
        action TEXT NOT NULL
            CHECK (action IN (
                'comment', 'request_evidence', 'resolve_continue',
                'resolve_reject', 'escalate', 'escalate_dispute', 'cancel'
            )),
        payload_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (review_case_id) REFERENCES review_cases(id)
    )""",
    """INSERT INTO review_actions (
        id, review_case_id, actor_user_id, acting_entity_id, action,
        payload_json, created_at
    ) SELECT id, review_case_id, actor_user_id, acting_entity_id, action,
             payload_json, created_at
        FROM review_actions_before_plan05_remediation""",
    "DROP TABLE review_actions_before_plan05_remediation",
    """CREATE INDEX idx_review_actions_case
        ON review_actions(review_case_id, created_at)""",
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
