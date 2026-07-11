"""Migration `008_documents_extraction_runs` + `009_rule_set_versions` testleri."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.db import connect, init_db


def _settings(path: Path) -> Settings:
    return Settings(db_path=path)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _insert_transaction(conn: sqlite3.Connection, transaction_id: str, lifecycle_version: str) -> None:
    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version) "
        "VALUES (?, 'uploaded', NULL, NULL, NULL, NULL, NULL, 'now', ?)",
        (transaction_id, lifecycle_version),
    )


def test_empty_db_gets_full_migration_chain(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "empty.db"))
    init_db(conn)
    versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == ["001", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014"]
    assert {
        "contract_documents",
        "extraction_runs",
        "rule_set_versions",
        "review_cases",
        "review_actions",
        "ratifications",
        "evidence_records",
        "disputes",
        "dispute_actions",
    } <= _tables(conn)
    conn.close()


def test_plan03_db_upgrades_additively_with_008_and_009(tmp_path: Path) -> None:
    """007'ye kadar migrate edilmiş bir DB (Plan 03 sonrası) 008/009'u sorunsuz alır."""
    from backend.app.db.migrations import (
        audit_events,
        baseline_current_schema,
        identity_sessions,
        legal_entities_memberships,
        participants_invitations,
        transaction_lifecycle_v2,
    )

    conn = connect(_settings(tmp_path / "plan03.db"))
    conn.execute(
        """CREATE TABLE schema_migrations (
            version TEXT PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
        )"""
    )
    for version, name, module in (
        ("001", "baseline_current_schema", baseline_current_schema),
        ("003", "identity_sessions", identity_sessions),
        ("004", "legal_entities_memberships", legal_entities_memberships),
        ("005", "participants_invitations", participants_invitations),
        ("006", "audit_events", audit_events),
        ("007", "transaction_lifecycle_v2", transaction_lifecycle_v2),
    ):
        module.apply(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, 'now')",
            (version, name),
        )
    conn.execute("INSERT INTO transactions (id, state) VALUES ('kept', 'uploaded')")
    conn.commit()

    init_db(conn)

    assert conn.execute("SELECT state FROM transactions WHERE id='kept'").fetchone()[0] == "uploaded"
    assert {"contract_documents", "extraction_runs", "rule_set_versions"} <= _tables(conn)
    versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == ["001", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014"]
    conn.close()


def test_migration_is_idempotent_across_repeated_runs(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "repeat.db"))
    init_db(conn)
    init_db(conn)
    init_db(conn)
    versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == ["001", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014"]
    conn.close()


def test_contract_documents_unique_transaction_and_version(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "docs.db"))
    init_db(conn)
    _insert_transaction(conn, "t1", "account_v2")
    conn.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) "
        "VALUES ('d1', 't1', 1, 'a.pdf', 'ref1', 'h1', 'active', 'now')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
            "storage_ref, content_sha256, status, created_at) "
            "VALUES ('d2', 't1', 1, 'b.pdf', 'ref2', 'h2', 'active', 'now')"
        )
    conn.close()


def test_contract_documents_unique_storage_ref(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "docs2.db"))
    init_db(conn)
    _insert_transaction(conn, "t1", "account_v2")
    _insert_transaction(conn, "t2", "account_v2")
    conn.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) "
        "VALUES ('d1', 't1', 1, 'a.pdf', 'shared-ref', 'h1', 'active', 'now')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
            "storage_ref, content_sha256, status, created_at) "
            "VALUES ('d2', 't2', 1, 'b.pdf', 'shared-ref', 'h2', 'active', 'now')"
        )
    conn.close()


def _insert_document(conn: sqlite3.Connection, doc_id: str, transaction_id: str) -> None:
    conn.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) "
        "VALUES (?, ?, 1, 'a.pdf', ?, 'h', 'active', 'now')",
        (doc_id, transaction_id, f"ref-{doc_id}"),
    )


def test_extraction_runs_reject_update_and_delete(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "runs.db"))
    init_db(conn)
    _insert_transaction(conn, "t1", "account_v2")
    _insert_document(conn, "d1", "t1")
    conn.execute(
        "INSERT INTO extraction_runs (id, transaction_id, document_id, provider, model, "
        "prompt_version, schema_version, status, created_at) "
        "VALUES ('r1', 't1', 'd1', 'fake', 'fake', 'v1', 'v1', 'ok', 'now')"
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE extraction_runs SET status = 'failed' WHERE id = 'r1'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM extraction_runs WHERE id = 'r1'")
    conn.close()


def test_rule_set_versions_unique_transaction_and_version(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "rsv.db"))
    init_db(conn)
    _insert_transaction(conn, "t1", "account_v2")
    conn.execute(
        "INSERT INTO rule_set_versions (id, transaction_id, version, rules_json, rules_hash, "
        "status, created_by_actor_type, created_at) "
        "VALUES ('r1', 't1', 1, '{}', 'h1', 'draft', 'system', 'now')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO rule_set_versions (id, transaction_id, version, rules_json, rules_hash, "
            "status, created_by_actor_type, created_at) "
            "VALUES ('r2', 't1', 1, '{}', 'h2', 'draft', 'system', 'now')"
        )
    conn.close()


def test_rule_set_versions_content_fields_are_immutable(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "rsv2.db"))
    init_db(conn)
    _insert_transaction(conn, "t1", "account_v2")
    conn.execute(
        "INSERT INTO rule_set_versions (id, transaction_id, version, rules_json, rules_hash, "
        "status, created_by_actor_type, created_at) "
        "VALUES ('r1', 't1', 1, '{\"a\":1}', 'h1', 'draft', 'system', 'now')"
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE rule_set_versions SET rules_json = '{\"a\":2}' WHERE id = 'r1'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE rule_set_versions SET rules_hash = 'other' WHERE id = 'r1'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE rule_set_versions SET version = 2 WHERE id = 'r1'")

    # status/validator alanları serbestçe güncellenebilir (immutable olan yalnız içerik).
    conn.execute("UPDATE rule_set_versions SET status = 'ratifiable', validator_status = 'PASS' WHERE id = 'r1'")
    row = conn.execute("SELECT status, validator_status FROM rule_set_versions WHERE id='r1'").fetchone()
    assert row["status"] == "ratifiable"
    assert row["validator_status"] == "PASS"
    conn.close()
