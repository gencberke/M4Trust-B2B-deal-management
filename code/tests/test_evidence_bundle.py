"""Plan 05 / Faz 5C — read-only bundle ve deterministic core testleri."""

from __future__ import annotations

import json

from backend.app.db import connect, init_db
from backend.app.services.evidence import build_bundle, build_bundle_core, compute_snapshot_hash
from reviews_fixtures import create_real_session, create_real_user


def _seed_account_transaction(monkeypatch, *, transaction_id: str = "tx-bundle"):
    conn = connect()
    init_db(conn)
    user_id = create_real_user(conn, email_normalized=f"{transaction_id}@example.com")
    session = create_real_session(conn, user_id=user_id)
    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id, "
        "created_by_user_id, content_sha256) VALUES (?, 'active', NULL, NULL, NULL, ?, ?, "
        "'2026-07-11T00:00:00+00:00', 'account_v2', 'entity-bundle', ?, 'hash')",
        (transaction_id, "raw PII markdown should never leave DB", "masked contract", user_id),
    )
    participant_id = f"participant-{transaction_id}"
    conn.execute(
        "INSERT INTO transaction_participants (id, transaction_id, role, legal_entity_id, "
        "status, created_at, updated_at) VALUES (?, ?, 'buyer', 'entity-bundle', 'confirmed', "
        "'now', 'now')",
        (participant_id, transaction_id),
    )
    conn.execute(
        "INSERT INTO transaction_assignments (id, transaction_id, participant_id, user_id, "
        "legal_entity_id, role, status, created_at) VALUES (?, ?, ?, ?, 'entity-bundle', "
        "'approver', 'active', 'now')",
        (f"assignment-{transaction_id}", transaction_id, participant_id, user_id),
    )
    conn.commit()
    conn.close()
    return transaction_id, user_id, session


def test_deterministic_core_hash_ignores_generated_at() -> None:
    core = {
        "transaction": {"id": "tx", "state": "active", "created_at": "t"},
        "events": [{"id": 1, "event_type": "x", "payload": {"n": 1}}],
    }
    first = compute_snapshot_hash(core)
    first_bundle = {**core, "generated_at": "2026-07-11T00:00:00+00:00"}
    second_bundle = {**core, "generated_at": "2026-07-11T00:01:00+00:00"}
    assert compute_snapshot_hash(
        {key: value for key, value in first_bundle.items() if key != "generated_at"}
    ) == first
    assert compute_snapshot_hash(
        {key: value for key, value in second_bundle.items() if key != "generated_at"}
    ) == first


def test_bundle_core_has_no_write_side_effect_and_redacts_optional_records(monkeypatch) -> None:
    transaction_id, _, _ = _seed_account_transaction(monkeypatch, transaction_id="tx-records")
    conn = connect()
    conn.execute(
        """CREATE TABLE evidence_records (
            id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL, evidence_type TEXT,
            source TEXT, verification_status TEXT, submitted_by_entity_id TEXT,
            external_reference TEXT, file_sha256 TEXT, analyzer_provider TEXT,
            analyzer_version TEXT, storage_ref TEXT, raw_payload TEXT,
            created_at TEXT, verified_at TEXT, milestone_id TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO evidence_records VALUES (?, ?, 'video', 'account', 'submitted', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "ev-1",
            transaction_id,
            "entity-bundle",
            "delivery-video-1",
            "a" * 64,
            "fake",
            "v1",
            "/secret/local/path.mp4",
            '{"email":"user@example.com","traceback":"secret"}',
            "now",
            None,
            None,
        ),
    )
    conn.commit()
    before = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    bundle = build_bundle(conn, transaction_id)
    after = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    conn.close()

    assert before == after == 0
    assert bundle["evidence_records"] == [
        {
            "id": "ev-1",
            "evidence_type": "video",
            "source": "account",
            "verification_status": "submitted",
            "submitted_by_entity_id": "entity-bundle",
            "submitted_by_role": None,
            "external_reference": "delivery-video-1",
            "file_sha256": "a" * 64,
            "analyzer_provider": "fake",
            "analyzer_version": "v1",
            "created_at": "now",
            "verified_at": None,
            "milestone_id": None,
        }
    ]
    serialized = json.dumps(bundle, ensure_ascii=False)
    assert "/secret/local/path.mp4" not in serialized
    assert "user@example.com" not in serialized
    assert "traceback" not in serialized


def test_bundle_core_and_response_hash_match(monkeypatch) -> None:
    transaction_id, _, _ = _seed_account_transaction(monkeypatch, transaction_id="tx-hash")
    conn = connect()
    core = build_bundle_core(conn, transaction_id)
    bundle = build_bundle(conn, transaction_id)
    conn.close()
    assert bundle["snapshot_hash"] == compute_snapshot_hash(core)
    assert bundle["generated_at"]
