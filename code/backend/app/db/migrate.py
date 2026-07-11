"""Fail-closed legacy stamping destekli atomik migration runner."""

from __future__ import annotations

import importlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from types import ModuleType


class UnknownLegacySchemaError(RuntimeError):
    """Migration metadata'sı olmayan DB tanınan şemayla eşleşmedi."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    module: ModuleType


_MIGRATION_MODULES = (
    "backend.app.db.migrations.001_baseline_current_schema",
    "backend.app.db.migrations.003_identity_sessions",
    "backend.app.db.migrations.004_legal_entities_memberships",
    "backend.app.db.migrations.005_participants_invitations",
    "backend.app.db.migrations.006_audit_events",
    "backend.app.db.migrations.007_transaction_lifecycle_v2",
    "backend.app.db.migrations.008_documents_extraction_runs",
    "backend.app.db.migrations.009_rule_set_versions",
    "backend.app.db.migrations.010_review_cases",
    "backend.app.db.migrations.011_ratification_packages",
    "backend.app.db.migrations.012_ratifications",
    "backend.app.db.migrations.013_evidence_records",
    "backend.app.db.migrations.014_disputes",
)

_LEGACY_COLUMNS = {
    "transactions": {"id", "state", "buyer_token", "seller_token", "manager_token", "markdown", "masked_markdown", "created_at"},
    "extracted_rules": {"transaction_id", "extraction_json", "validator_status", "validator_report", "created_at"},
    "approvals": {"transaction_id", "party", "created_at"},
    "events": {"id", "transaction_id", "event_type", "payload", "source", "created_at"},
    "mock_payments": {"transaction_id", "other_trx_code", "virtual_pos_order_id", "status", "amount", "created_at"},
    "evidence": {"transaction_id", "bundle_json", "created_at"},
    "tracking_policies": {"transaction_id", "recommendation", "recommendation_reason_codes", "manager_physical_delivery_confirmed", "tracking_mode", "video_role", "status", "configured_at", "locked_at"},
}


def _migrations() -> tuple[Migration, ...]:
    result = []
    for path in _MIGRATION_MODULES:
        module = importlib.import_module(path)
        result.append(Migration(module.VERSION, module.NAME, module))
    return tuple(result)


def _user_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _is_recognized_legacy(conn: sqlite3.Connection, tables: set[str]) -> bool:
    if tables != set(_LEGACY_COLUMNS):
        return False
    return all(
        {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')} == columns
        for table, columns in _LEGACY_COLUMNS.items()
    )


def _create_metadata(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE schema_migrations (
            version TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )"""
    )


def _mark_applied(conn: sqlite3.Connection, migration: Migration) -> None:
    conn.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (migration.version, migration.name, datetime.now(timezone.utc).isoformat()),
    )


def run_migrations(conn: sqlite3.Connection) -> None:
    migrations = _migrations()
    tables = _user_tables(conn)

    if "schema_migrations" not in tables:
        if tables and not _is_recognized_legacy(conn, tables):
            raise UnknownLegacySchemaError(
                f"Tanınmayan legacy şema; mutation uygulanmadı: {sorted(tables)}"
            )
        conn.execute("BEGIN IMMEDIATE")
        try:
            _create_metadata(conn)
            if tables:
                _mark_applied(conn, migrations[0])
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    applied = {
        row[0] for row in conn.execute("SELECT version FROM schema_migrations")
    }
    for migration in migrations:
        if migration.version in applied:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            migration.module.apply(conn)
            _mark_applied(conn, migration)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def init_db(conn: sqlite3.Connection) -> None:
    run_migrations(conn)
