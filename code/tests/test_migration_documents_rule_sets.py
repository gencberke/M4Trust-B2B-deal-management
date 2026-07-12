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
    assert versions == ["001", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014", "015", "016", "017", "018", "023", "024"]
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
    assert versions == ["001", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014", "015", "016", "017", "018", "023", "024"]
    conn.close()


def test_plan06_provider_tables_survive_024_rebuild(tmp_path: Path) -> None:
    """016/017'ye kadar migrate edilmiş bir DB (Plan 06 sonrası) 024'ün rebuild-and-copy
    dansına veri kaybetmeden girip çıkmalı (provider_payments/provider_operations/
    release_instructions/fake_provider_payments ALTER TABLE RENAME + rebuild kullanır)."""

    from backend.app.db import migrate as migrate_module

    conn = connect(_settings(tmp_path / "plan06.db"))
    conn.execute(
        """CREATE TABLE schema_migrations (
            version TEXT PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
        )"""
    )
    pre_024 = [m for m in migrate_module._migrations() if m.version not in {"018", "023", "024"}]
    for migration in pre_024:
        migration.module.apply(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, 'now')",
            (migration.version, migration.name),
        )

    _insert_transaction(conn, "tx-p6", "account_v2")
    _insert_document(conn, "doc-p6", "tx-p6")
    conn.execute(
        "INSERT INTO rule_set_versions (id, transaction_id, version, rules_json, rules_hash, "
        "status, created_by_actor_type, created_at) "
        "VALUES ('rsv-p6', 'tx-p6', 1, '{}', 'rsv-hash-p6', 'ratifiable', 'system', 'now')"
    )
    conn.execute(
        """INSERT INTO ratification_packages (
            id, transaction_id, version, document_id, rule_set_version_id,
            tracking_policy_version_id, canonical_payload_json, document_hash,
            rule_set_hash, participant_snapshot_hash, tracking_policy_hash,
            package_hash, status, created_at, opened_at, completed_at
        ) VALUES ('pkg-p6', 'tx-p6', 1, 'doc-p6', 'rsv-p6', NULL, '{}', 'h1', 'h2', 'h3', 'h4',
                  'h5', 'complete', 'now', 'now', 'now')"""
    )
    conn.execute(
        """INSERT INTO milestones (
            id, transaction_id, ratification_package_id, rule_set_version_id, rule_index,
            title, trigger_type, percentage_basis_points, amount_minor, currency,
            required_evidence_json, release_mode, status, released_amount_minor,
            created_at, updated_at
        ) VALUES ('ms-p6', 'tx-p6', 'pkg-p6', 'rsv-p6', 0, 'Teslimat', 'delivery',
                  10000, 1000, 'TRY', '[]', 'fixed_tranches', 'released', 1000, 'now', 'now')"""
    )
    conn.execute(
        """INSERT INTO funding_units (
            id, transaction_id, ratification_package_id, milestone_id, sequence, title,
            amount_minor, currency, eligibility_type, eligibility_payload_json,
            provider_profile, other_trx_code, status, created_at, updated_at
        ) VALUES ('fu-p6', 'tx-p6', 'pkg-p6', 'ms-p6', 1, 'Unit 1', 1000, 'TRY',
                  'verified_quantity', '{}', 'moka_standard_v1', 'M4T-p6-U01',
                  'approved', 'now', 'now')"""
    )
    conn.execute(
        """INSERT INTO provider_payments (
            id, funding_unit_id, provider_profile, other_trx_code, virtual_pos_order_id,
            dealer_payment_id, internal_status, moka_payment_status, moka_trx_status,
            amount_minor, currency, last_result_code, last_result_message,
            created_at, updated_at
        ) VALUES ('pp-p6', 'fu-p6', 'moka_standard_v1', 'M4T-p6-U01', 'VPOS-p6', 'DP-p6',
                  'approved', 2, 1, 1000, 'TRY', 'OK', 'onaylandi', 'now', 'now')"""
    )
    conn.execute(
        """INSERT INTO provider_operations (
            id, provider_payment_id, funding_unit_id, operation_type, endpoint,
            idempotency_key, request_fingerprint, redacted_request_json, response_json,
            http_status, result_code, is_successful, outcome, attempt_no, created_at
        ) VALUES ('po-p6', 'pp-p6', 'fu-p6', 'approve_pool_payment', 'ApprovePoolPayment',
                  'idem-p6', 'fp-p6', '{}', '{}', 200, 'OK', 1, 'success', 1, 'now')"""
    )
    conn.execute(
        """INSERT INTO release_instructions (
            id, funding_unit_id, provider_payment_id, operation_type, amount_minor,
            currency, idempotency_key, status, provider, provider_reference,
            created_at, updated_at
        ) VALUES ('ri-p6', 'fu-p6', 'pp-p6', 'approve_pool_payment', 1000, 'TRY',
                  'ri-idem-p6', 'confirmed', 'moka_standard_v1', 'VPOS-p6', 'now', 'now')"""
    )
    conn.execute(
        """INSERT INTO fake_provider_payments (
            id, other_trx_code, virtual_pos_order_id, amount_minor, currency, status,
            is_pool_payment, created_at, updated_at
        ) VALUES ('fpp-p6', 'M4T-p6-U01', 'VPOS-p6', 1000, 'TRY', 'approved', 1, 'now', 'now')"""
    )
    conn.commit()

    init_db(conn)

    versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == ["001", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014", "015", "016", "017", "018", "023", "024"]

    provider_payment = conn.execute("SELECT * FROM provider_payments WHERE id = 'pp-p6'").fetchone()
    assert provider_payment["internal_status"] == "approved"
    assert provider_payment["other_trx_code"] == "M4T-p6-U01"
    assert provider_payment["dealer_payment_id"] == "DP-p6"
    assert provider_payment["amount_minor"] == 1000

    operation = conn.execute("SELECT * FROM provider_operations WHERE id = 'po-p6'").fetchone()
    assert operation["idempotency_key"] == "idem-p6"
    assert operation["attempt_no"] == 1

    instruction = conn.execute("SELECT * FROM release_instructions WHERE id = 'ri-p6'").fetchone()
    assert instruction["status"] == "confirmed"
    assert instruction["idempotency_key"] == "ri-idem-p6"

    fake_payment = conn.execute("SELECT * FROM fake_provider_payments WHERE id = 'fpp-p6'").fetchone()
    assert fake_payment["status"] == "approved"
    assert fake_payment["other_trx_code"] == "M4T-p6-U01"

    # 024 öncesi CHECK constraint'i reddederdi; rebuild sonrası yeni durumlar kabul edilir.
    conn.execute(
        "UPDATE provider_payments SET internal_status = 'refunded' WHERE id = 'pp-p6'"
    )
    conn.execute(
        "UPDATE fake_provider_payments SET status = 'refunded' WHERE id = 'fpp-p6'"
    )
    conn.commit()

    assert conn.execute("SELECT COUNT(*) FROM payment_resolutions").fetchone()[0] == 0
    assert {"payment_resolutions", "payment_resolution_approvals"} <= _tables(conn)
    conn.close()


def test_migration_is_idempotent_across_repeated_runs(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "repeat.db"))
    init_db(conn)
    init_db(conn)
    init_db(conn)
    versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == ["001", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014", "015", "016", "017", "018", "023", "024"]
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
