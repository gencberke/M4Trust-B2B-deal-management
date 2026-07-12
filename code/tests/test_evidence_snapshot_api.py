"""Plan 05 / Faz 5C — account bundle/snapshot API contract testleri."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from backend.app.db import connect
from backend.app.main import app
from backend.app.services.audit import AuditActor
from backend.app.services.evidence import build_bundle
from reviews_fixtures import create_real_session, create_real_user


def _seed_transaction(*, transaction_id: str = "tx-snapshot"):
    conn = connect()
    user_id = create_real_user(conn, email_normalized=f"{transaction_id}@example.com")
    session = create_real_session(conn, user_id=user_id)
    conn.execute(
        "INSERT OR IGNORE INTO legal_entities (id, entity_type, legal_name, "
        "tax_identifier_type, tax_identifier_ciphertext, tax_identifier_lookup_hmac, "
        "tax_identifier_last4, verification_status, created_by_user_id, created_at, updated_at) "
        "VALUES ('entity-snapshot', 'company', 'Snapshot Entity', 'vkn', 'cipher', "
        "'snapshot-hmac', '0000', 'self_declared', ?, 'now', 'now')",
        (user_id,),
    )
    conn.execute(
        "INSERT INTO memberships (id, user_id, legal_entity_id, role, status, created_at) "
        "VALUES (?, ?, 'entity-snapshot', 'owner', 'active', 'now')",
        (f"membership-{transaction_id}", user_id),
    )
    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id, "
        "created_by_user_id, content_sha256) VALUES (?, 'active', NULL, NULL, NULL, NULL, NULL, "
        "'now', 'account_v2', 'entity-snapshot', ?, 'hash')",
        (transaction_id, user_id),
    )
    participant_id = f"participant-{transaction_id}"
    conn.execute(
        "INSERT INTO transaction_participants (id, transaction_id, role, legal_entity_id, "
        "status, created_at, updated_at) VALUES (?, ?, 'seller', 'entity-snapshot', 'confirmed', "
        "'now', 'now')",
        (participant_id, transaction_id),
    )
    conn.execute(
        "INSERT INTO transaction_assignments (id, transaction_id, participant_id, user_id, "
        "legal_entity_id, role, status, created_at) VALUES (?, ?, ?, ?, 'entity-snapshot', "
        "'approver', 'active', 'now')",
        (f"assignment-{transaction_id}", transaction_id, participant_id, user_id),
    )
    conn.commit()
    conn.close()
    return transaction_id, user_id, session


def _auth(client: TestClient, session) -> None:
    client.cookies.set("m4t_session", session.raw_token)
    client.cookies.set("m4t_csrf", session.raw_csrf_token)
    client.headers["X-Acting-Entity-ID"] = "entity-snapshot"


def test_account_bundle_requires_auth_and_assignment(client: TestClient) -> None:
    transaction_id, _, owner_session = _seed_transaction(transaction_id="tx-auth")
    anonymous = client.get(f"/api/transactions/{transaction_id}/evidence-bundle")
    assert anonymous.status_code == 401

    outsider_user_id = None
    conn = connect()
    outsider_user_id = create_real_user(conn, email_normalized="outsider-snapshot@example.com")
    outsider_session = create_real_session(conn, user_id=outsider_user_id)
    conn.commit()
    conn.close()
    _auth(client, outsider_session)
    forbidden = client.get(f"/api/transactions/{transaction_id}/evidence-bundle")
    assert forbidden.status_code == 403

    _auth(client, owner_session)
    allowed = client.get(f"/api/transactions/{transaction_id}/evidence-bundle")
    assert allowed.status_code == 200, allowed.text


def test_get_bundle_is_read_only_and_repeated_get_does_not_snapshot(client: TestClient) -> None:
    transaction_id, _, session = _seed_transaction(transaction_id="tx-readonly")
    _auth(client, session)
    conn = connect()
    before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("evidence", "audit_events", "events")
    }
    conn.close()

    first = client.get(f"/api/transactions/{transaction_id}/evidence-bundle")
    second = client.get(f"/api/transactions/{transaction_id}/evidence-bundle")
    assert first.status_code == second.status_code == 200
    assert first.json()["snapshot_hash"] == second.json()["snapshot_hash"]

    conn = connect()
    after = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("evidence", "audit_events", "events")
    }
    conn.close()
    assert after == before


def test_snapshot_post_is_explicit_and_exact_replay_is_idempotent(client: TestClient) -> None:
    transaction_id, _, session = _seed_transaction(transaction_id="tx-idempotent")
    _auth(client, session)
    url = f"/api/transactions/{transaction_id}/evidence-snapshots"

    missing_csrf = client.post(url)
    assert missing_csrf.status_code == 403

    first = client.post(url, headers={"X-CSRF-Token": session.raw_csrf_token})
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["created"] is True

    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action = 'evidence_snapshot.created'"
        ).fetchone()[0]
        == 1
    )
    conn.close()

    replay = client.post(url, headers={"X-CSRF-Token": session.raw_csrf_token})
    assert replay.status_code == 200, replay.text
    replay_body = replay.json()
    assert replay_body["created"] is False
    assert replay_body["snapshot_id"] == first_body["snapshot_id"]
    assert replay_body["snapshot_hash"] == first_body["snapshot_hash"]
    assert replay_body["bundle"] == first_body["bundle"]

    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action = 'evidence_snapshot.created'"
        ).fetchone()[0]
        == 1
    )
    conn.close()


def test_changed_state_creates_new_snapshot(client: TestClient) -> None:
    transaction_id, _, session = _seed_transaction(transaction_id="tx-changed")
    _auth(client, session)
    url = f"/api/transactions/{transaction_id}/evidence-snapshots"

    first = client.post(url, headers={"X-CSRF-Token": session.raw_csrf_token}).json()
    conn = connect()
    conn.execute("UPDATE transactions SET state = 'evidence_pending' WHERE id = ?", (transaction_id,))
    conn.commit()
    conn.close()
    second = client.post(url, headers={"X-CSRF-Token": session.raw_csrf_token}).json()

    assert second["created"] is True
    assert second["snapshot_id"] != first["snapshot_id"]
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 2
    conn.close()


def test_legacy_get_is_flagged_deprecated_and_read_only(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("LEGACY_CAPABILITY_ACCESS_ENABLED", "true")
    conn = connect()
    transaction_id = "tx-legacy-readonly"
    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at) VALUES (?, 'active', 'buyer-secret', "
        "'seller-secret', 'manager-secret', NULL, NULL, 'now')",
        (transaction_id,),
    )
    conn.commit()
    conn.close()

    response = client.get(
        f"/api/transactions/{transaction_id}/evidence", params={"token": "buyer-secret"}
    )
    assert response.status_code == 200, response.text
    assert response.headers["Deprecation"] == "true"
    assert "evidence-bundle" in response.headers["Link"]

    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
    conn.close()

    monkeypatch.setenv("LEGACY_CAPABILITY_ACCESS_ENABLED", "false")
    denied = client.get(
        f"/api/transactions/{transaction_id}/evidence", params={"token": "buyer-secret"}
    )
    assert denied.status_code == 403
