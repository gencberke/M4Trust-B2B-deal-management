"""Corrective immutability trigger after migrations 022/023/024."""

from __future__ import annotations

import sqlite3

VERSION = "025"
NAME = "plan09_provenance_constraints"

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
          OR COALESCE(NEW.analyzer_model, '') != COALESCE(OLD.analyzer_model, '')
          OR COALESCE(NEW.analyzer_model_version, '') != COALESCE(OLD.analyzer_model_version, '')
          OR NEW.created_at != OLD.created_at
        BEGIN
            SELECT RAISE(ABORT, 'evidence_records bound fields are immutable');
        END""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
