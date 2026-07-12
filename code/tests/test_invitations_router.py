"""`routers/invitations.py` — izole app + StubActor ile API-seviyesi testler."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.services.access_control import ActorContext
from backend.app.services.notifications import FakeNotificationProvider
from backend.app.services import participants as participants_svc
from participants_fixtures import (
    build_isolated_app,
    create_test_membership,
    create_test_transaction,
    create_test_user,
    make_participants_db,
)


@pytest.fixture()
def conn():
    connection = make_participants_db()
    try:
        yield connection
    finally:
        connection.close()


def actor(user_id="u1", entity_id="entity-1") -> ActorContext:
    return ActorContext(
        actor_type="user",
        user_id=user_id,
        acting_entity_id=entity_id,
        request_id="req-1",
    )


ANONYMOUS = ActorContext(actor_type="anonymous")


def test_create_invitation_requires_auth(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    app = build_isolated_app(conn, ANONYMOUS, notification_provider=FakeNotificationProvider())
    client = TestClient(app)

    response = client.post(
        f"/api/transactions/{tx_id}/invitations",
        json={"participant_role": "seller", "invited_email": "party@example.com"},
    )
    assert response.status_code == 401


def test_create_invitation_forbidden_for_non_manager(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    app = build_isolated_app(conn, actor("someone-else"), notification_provider=FakeNotificationProvider())
    client = TestClient(app)

    response = client.post(
        f"/api/transactions/{tx_id}/invitations",
        json={"participant_role": "seller", "invited_email": "party@example.com"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "INVITATION_FORBIDDEN"


def test_create_invitation_success_returns_link_with_request_id_header(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    app = build_isolated_app(conn, actor("u1"), notification_provider=FakeNotificationProvider())
    client = TestClient(app)

    response = client.post(
        f"/api/transactions/{tx_id}/invitations",
        json={"participant_role": "seller", "invited_email": "party@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "invite_link" in body
    assert "X-Request-ID" in response.headers


def test_preview_invitation_no_auth_required_and_no_pii(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    app = build_isolated_app(conn, actor("u1"), notification_provider=provider)
    client = TestClient(app)

    create_resp = client.post(
        f"/api/transactions/{tx_id}/invitations",
        json={"participant_role": "seller", "invited_email": "party@example.com"},
    )
    invite_link = create_resp.json()["invite_link"]
    token = invite_link.split("/api/invitations/")[1].split("/accept")[0]

    anon_app = build_isolated_app(conn, ANONYMOUS)
    anon_client = TestClient(anon_app)
    preview_resp = anon_client.get(f"/api/invitations/{token}/preview")

    assert preview_resp.status_code == 200
    body = preview_resp.json()
    assert body["participant_role"] == "seller"
    assert "party@example.com" not in preview_resp.text
    assert "entity-1" not in preview_resp.text


def test_preview_invitation_get_is_not_a_write(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    app = build_isolated_app(conn, actor("u1"), notification_provider=provider)
    client = TestClient(app)

    create_resp = client.post(
        f"/api/transactions/{tx_id}/invitations",
        json={"participant_role": "seller", "invited_email": "party@example.com"},
    )
    token = create_resp.json()["invite_link"].split("/api/invitations/")[1].split("/accept")[0]

    client.get(f"/api/invitations/{token}/preview")
    client.get(f"/api/invitations/{token}/preview")

    row = conn.execute(
        "SELECT status, accepted_at FROM transaction_invitations WHERE transaction_id = ?", (tx_id,)
    ).fetchone()
    assert row["status"] == "pending"
    assert row["accepted_at"] is None


def test_accept_invitation_end_to_end(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    app = build_isolated_app(conn, actor("u1"), notification_provider=provider)
    client = TestClient(app)

    create_resp = client.post(
        f"/api/transactions/{tx_id}/invitations",
        json={"participant_role": "seller", "invited_email": "party@example.com"},
    )
    token = create_resp.json()["invite_link"].split("/api/invitations/")[1].split("/accept")[0]

    create_test_user(conn, email_normalized="party@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2")

    acceptor_app = build_isolated_app(conn, actor("u2", "entity-2"))
    acceptor_client = TestClient(acceptor_app)
    accept_resp = acceptor_client.post(
        f"/api/invitations/{token}/accept", json={"legal_entity_id": "entity-2"}
    )

    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "ready"
    assert accept_resp.json()["legal_entity_id"] == "entity-2"


def test_accept_invitation_wrong_email_returns_403(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    app = build_isolated_app(conn, actor("u1"), notification_provider=provider)
    client = TestClient(app)

    create_resp = client.post(
        f"/api/transactions/{tx_id}/invitations",
        json={"participant_role": "seller", "invited_email": "party@example.com"},
    )
    token = create_resp.json()["invite_link"].split("/api/invitations/")[1].split("/accept")[0]

    create_test_user(conn, email_normalized="different@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2")

    acceptor_app = build_isolated_app(conn, actor("u2", "entity-2"))
    response = TestClient(acceptor_app).post(
        f"/api/invitations/{token}/accept", json={"legal_entity_id": "entity-2"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "INVITATION_EMAIL_MISMATCH"


def test_accept_invitation_rejects_body_entity_without_matching_acting_entity(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    creator = TestClient(build_isolated_app(conn, actor("u1"), notification_provider=provider))
    create_resp = creator.post(
        f"/api/transactions/{tx_id}/invitations",
        json={"participant_role": "seller", "invited_email": "party@example.com"},
    )
    token = create_resp.json()["invite_link"].split("/api/invitations/")[1].split("/accept")[0]
    create_test_user(conn, email_normalized="party@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2")

    response = TestClient(build_isolated_app(conn, actor("u2", "entity-other"))).post(
        f"/api/invitations/{token}/accept", json={"legal_entity_id": "entity-2"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "INVITATION_FORBIDDEN"


def test_revoke_invitation_by_manager(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    app = build_isolated_app(conn, actor("u1"), notification_provider=provider)
    client = TestClient(app)

    create_resp = client.post(
        f"/api/transactions/{tx_id}/invitations",
        json={"participant_role": "seller", "invited_email": "party@example.com"},
    )
    invitation_id = conn.execute(
        "SELECT id FROM transaction_invitations WHERE transaction_id = ?", (tx_id,)
    ).fetchone()["id"]

    revoke_resp = client.post(f"/api/transactions/{tx_id}/invitations/{invitation_id}/revoke")
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "revoked"


def test_revoke_invitation_by_unrelated_user_returns_403(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    app = build_isolated_app(conn, actor("u1"), notification_provider=provider)
    client = TestClient(app)
    create_resp = client.post(
        f"/api/transactions/{tx_id}/invitations",
        json={"participant_role": "seller", "invited_email": "party@example.com"},
    )
    invitation_id = conn.execute(
        "SELECT id FROM transaction_invitations WHERE transaction_id = ?", (tx_id,)
    ).fetchone()["id"]

    other_app = build_isolated_app(conn, actor("unrelated-user"))
    response = TestClient(other_app).post(
        f"/api/transactions/{tx_id}/invitations/{invitation_id}/revoke"
    )
    assert response.status_code == 403
