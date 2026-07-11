"""Plan 05 / Faz 5A — `services/evidence_records.py` servis-katmanı testleri.

Router/HTTP yok; `submit_evidence`/`collect_transaction_delivery_evidence`
doğrudan çağrılır. Router-seviyesi authorization testleri
`test_evidence_submit_api.py`'dedir.
"""

from __future__ import annotations

import ast
import json
from importlib import import_module
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.services import evidence_records as svc
from backend.app.services.access_control import ActorContext

_evidence_migration = import_module("backend.app.db.migrations.013_evidence_records")


def _actor(user_id: str = "u-buyer", entity_id: str = "entity-buyer") -> ActorContext:
    return ActorContext(
        actor_type="user", user_id=user_id, acting_entity_id=entity_id,
        auth_method="session", request_id="req-5a",
    )


def _create_user(conn, user_id: str, email: str) -> None:
    conn.execute(
        "INSERT INTO users (id, email_normalized, password_hash, first_name, last_name, "
        "status, platform_role, created_at, updated_at) VALUES (?, ?, 'unused', 'T', 'U', "
        "'active', NULL, datetime('now'), datetime('now'))",
        (user_id, email),
    )


def _create_entity(conn, entity_id: str, created_by_user_id: str) -> None:
    conn.execute(
        "INSERT INTO legal_entities (id, entity_type, legal_name, tax_identifier_type, "
        "tax_identifier_ciphertext, tax_identifier_lookup_hmac, tax_identifier_last4, "
        "verification_status, created_by_user_id, created_at, updated_at) "
        "VALUES (?, 'company', ?, 'vkn', 'cipher', 'hmac', '1234', 'self_declared', ?, "
        "datetime('now'), datetime('now'))",
        (entity_id, f"Legal Entity {entity_id}", created_by_user_id),
    )


@pytest.fixture()
def conn(tmp_path: Path):
    connection = connect(Settings(db_path=tmp_path / "5a.db"))
    init_db(connection)
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_records'"
    ).fetchone() is None:
        _evidence_migration.apply(connection)
    _create_user(connection, "u-buyer", "buyer@example.com")
    _create_entity(connection, "entity-buyer", "u-buyer")
    connection.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES ('tx-5a', 'awaiting_ratification', NULL, NULL, NULL, NULL, NULL, 'now', "
        "'account_v2', 'entity-buyer')"
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def _submit_e_irsaliye(conn, *, external_reference="ext-1", delivered_quantity=10.0, actor=None):
    return svc.submit_evidence(
        conn,
        transaction_id="tx-5a",
        milestone_id=None,
        evidence_type="e_irsaliye",
        source="external_api",
        actor_context=actor or _actor(),
        payload={"delivered_quantity": delivered_quantity},
        verification_status="verified",
        external_reference=external_reference,
    )


# --- migration smoke ---------------------------------------------------------------


def test_migration_is_additive_and_rerun_safe(tmp_path: Path) -> None:
    connection = connect(Settings(db_path=tmp_path / "smoke.db"))
    init_db(connection)
    init_db(connection)
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_records'"
    ).fetchone() is not None
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='evidence_records'"
    ).fetchone()
    assert row is not None
    with pytest.raises(Exception):
        _evidence_migration.apply(connection)  # tekrar çalıştırma CREATE TABLE ile çakışmalı
    connection.close()


def test_evidence_records_append_only_no_delete(conn) -> None:
    record = _submit_e_irsaliye(conn)
    with pytest.raises(Exception):
        conn.execute("DELETE FROM evidence_records WHERE id = ?", (record.id,))


def test_evidence_records_bound_fields_immutable(conn) -> None:
    record = _submit_e_irsaliye(conn)
    with pytest.raises(Exception):
        conn.execute(
            "UPDATE evidence_records SET payload_json = '{}' WHERE id = ?", (record.id,)
        )


def test_evidence_provenance_fields_are_immutable(conn) -> None:
    record = svc.submit_evidence(
        conn,
        transaction_id="tx-5a",
        milestone_id=None,
        evidence_type="video",
        source="analyzer",
        actor_context=_actor(),
        payload={"counts": {}, "unit_count": 1, "damage_signals": [], "confidence": 0.9},
        verification_status="verified",
        storage_ref="tx-5a/video-provenance",
        file_sha256="c" * 64,
        analyzer_provider="fake",
        analyzer_version="v1",
    )
    with pytest.raises(Exception):
        conn.execute(
            "UPDATE evidence_records SET analyzer_provider = 'other' WHERE id = ?",
            (record.id,),
        )
    with pytest.raises(Exception):
        conn.execute(
            "UPDATE evidence_records SET analyzer_version = 'v2' WHERE id = ?",
            (record.id,),
        )


# --- idempotency ---------------------------------------------------------------------


def test_exact_replay_returns_same_record_id(conn) -> None:
    first = _submit_e_irsaliye(conn)
    second = _submit_e_irsaliye(conn)
    assert first.id == second.id


def test_duplicate_replay_does_not_emit_second_event(conn) -> None:
    _submit_e_irsaliye(conn)
    _submit_e_irsaliye(conn)
    count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE transaction_id = 'tx-5a' AND event_type = 'evidence_submitted'"
    ).fetchone()[0]
    assert count == 1


def test_same_external_reference_different_content_is_conflict(conn) -> None:
    _submit_e_irsaliye(conn, external_reference="ext-1", delivered_quantity=10.0)
    with pytest.raises(svc.EvidenceIdempotencyConflictError) as exc:
        _submit_e_irsaliye(conn, external_reference="ext-1", delivered_quantity=99.0)
    assert exc.value.code == "EVIDENCE_IDEMPOTENCY_CONFLICT"


def test_video_storage_ref_and_sha256_are_recorded(conn) -> None:
    record = svc.submit_evidence(
        conn, transaction_id="tx-5a", milestone_id=None, evidence_type="video", source="analyzer",
        actor_context=_actor(), payload={"counts": {}, "unit_count": 10, "damage_signals": [], "confidence": 0.9},
        verification_status="verified", storage_ref="tx-5a/doc-1", file_sha256="a" * 64,
        analyzer_provider="fake", analyzer_version="video_analyzer_v1",
    )
    assert record.storage_ref == "tx-5a/doc-1"
    assert record.file_sha256 == "a" * 64


def test_record_carries_actor_user_and_entity(conn) -> None:
    record = _submit_e_irsaliye(conn, actor=_actor("u-buyer", "entity-buyer"))
    assert record.submitted_by_user_id == "u-buyer"
    assert record.submitted_by_entity_id == "entity-buyer"


def test_e_irsaliye_external_reference_is_persisted(conn) -> None:
    record = _submit_e_irsaliye(conn, external_reference="irsaliye-42")
    assert record.external_reference == "irsaliye-42"
    assert record.payload == {"delivered_quantity": 10.0}


# --- event/audit payload safety -------------------------------------------------------


def test_event_payload_carries_no_raw_secret_marker(conn) -> None:
    marker = "SECRET-MARKER-" + uuid4().hex
    svc.submit_evidence(
        conn, transaction_id="tx-5a", milestone_id=None, evidence_type="e_irsaliye",
        source="external_api", actor_context=_actor(),
        payload={"delivered_quantity": 5.0, "note": marker}, verification_status="verified",
        external_reference="ext-marker",
    )
    rows = conn.execute("SELECT * FROM events WHERE transaction_id = 'tx-5a'").fetchall()
    for row in rows:
        assert marker not in json.dumps(dict(row))
    audit_rows = conn.execute("SELECT * FROM audit_events WHERE transaction_id = 'tx-5a'").fetchall()
    for row in audit_rows:
        assert marker not in json.dumps(dict(row))


# --- account/legacy adapter ------------------------------------------------------------


def test_account_adapter_reads_evidence_records(conn) -> None:
    _submit_e_irsaliye(conn, delivered_quantity=42.0)
    svc.submit_evidence(
        conn, transaction_id="tx-5a", milestone_id=None, evidence_type="video", source="analyzer",
        actor_context=_actor(), payload={"counts": {}, "unit_count": 5, "damage_signals": [], "confidence": 0.9},
        verification_status="verified", storage_ref="tx-5a/doc-2", file_sha256="b" * 64,
    )
    evidence = svc.collect_transaction_delivery_evidence(conn, "tx-5a")
    assert evidence.e_irsaliye == {"delivered_quantity": 42.0}
    assert evidence.video["unit_count"] == 5


def test_legacy_adapter_reads_existing_event_path(tmp_path: Path) -> None:
    connection = connect(Settings(db_path=tmp_path / "legacy.db"))
    init_db(connection)
    connection.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at) VALUES ('tx-legacy', 'active', 'b', 's', 'm', "
        "'', '', datetime('now'))"
    )
    from backend.app.eventbus import emit

    emit(connection, "tx-legacy", "e_irsaliye_received", {"delivered_quantity": 7.0}, "e_irsaliye")
    emit(
        connection, "tx-legacy", "delivery_video_analyzed",
        {"counts": {}, "unit_count": 3, "damage_signals": [], "confidence": 0.9}, "video",
    )
    connection.commit()

    evidence = svc.collect_transaction_delivery_evidence(connection, "tx-legacy")
    assert evidence.e_irsaliye == {"delivered_quantity": 7.0}
    assert evidence.video["unit_count"] == 3
    connection.close()


def test_rejected_record_is_not_used_by_account_adapter(conn) -> None:
    record = _submit_e_irsaliye(conn, delivered_quantity=10.0)
    svc.verify_evidence(conn, evidence_id=record.id, verification_status="rejected", actor_context=_actor())
    evidence = svc.collect_transaction_delivery_evidence(conn, "tx-5a")
    assert evidence.e_irsaliye is None


# --- isolation: no provider import -----------------------------------------------------


def test_evidence_records_module_imports_no_payment_provider() -> None:
    module_path = (
        Path(__file__).resolve().parents[1] / "backend" / "app" / "services" / "evidence_records.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    forbidden_prefixes = (
        "backend.app.services.payment_provider",
        "backend.app.services.payments.moka",
        "backend.app.services.payments.ports",
        "fastapi",
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in imported:
        assert not any(name == p or name.startswith(p + ".") for p in forbidden_prefixes), name
