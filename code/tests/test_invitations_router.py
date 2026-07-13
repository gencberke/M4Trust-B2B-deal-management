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


# --- Plan 14 / P2: invitation list + reissue --------------------------------


def _create_seller_invitation(conn, client, tx_id: str, email: str = "party@example.com") -> str:
    resp = client.post(
        f"/api/transactions/{tx_id}/invitations",
        json={"participant_role": "seller", "invited_email": email},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["invite_link"].split("/api/invitations/")[1].split("/accept")[0]


def test_list_invitations_manager_scoped(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    manager = TestClient(build_isolated_app(conn, actor("u1"), notification_provider=FakeNotificationProvider()))
    _create_seller_invitation(conn, manager, tx_id)

    resp = manager.get(f"/api/transactions/{tx_id}/invitations")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["participant_role"] == "seller"
    assert body[0]["invited_email"] == "party@example.com"
    assert body[0]["status"] == "pending"


def test_list_invitations_forbidden_for_non_manager(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    outsider = TestClient(build_isolated_app(conn, actor("intruder", "entity-x")))
    resp = outsider.get(f"/api/transactions/{tx_id}/invitations")
    assert resp.status_code == 403
    assert resp.json()["code"] == "INVITATION_FORBIDDEN"


def test_reissue_supersedes_old_token(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    manager = TestClient(build_isolated_app(conn, actor("u1"), notification_provider=FakeNotificationProvider()))
    old_token = _create_seller_invitation(conn, manager, tx_id)
    old_invitation_id = conn.execute(
        "SELECT id FROM transaction_invitations WHERE transaction_id = ?", (tx_id,)
    ).fetchone()["id"]

    reissue_resp = manager.post(
        f"/api/transactions/{tx_id}/invitations/{old_invitation_id}/reissue"
    )
    assert reissue_resp.status_code == 200
    new_token = reissue_resp.json()["invite_link"].split("/api/invitations/")[1].split("/accept")[0]
    assert new_token != old_token

    # Eski davet supersede edildi (revoked); yeni davet pending.
    statuses = {
        row["id"]: row["status"]
        for row in conn.execute(
            "SELECT id, status FROM transaction_invitations WHERE transaction_id = ?", (tx_id,)
        ).fetchall()
    }
    assert statuses[old_invitation_id] == "revoked"

    create_test_user(conn, email_normalized="party@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2")
    conn.commit()  # başarısız accept isteği conn'u rollback etmesin (isolated app get_db)
    acceptor = TestClient(build_isolated_app(conn, actor("u2", "entity-2")))

    # Eski token artık accept edilemez; taze token bağlanır.
    old_accept = acceptor.post(f"/api/invitations/{old_token}/accept", json={"legal_entity_id": "entity-2"})
    assert old_accept.status_code == 409
    new_accept = acceptor.post(f"/api/invitations/{new_token}/accept", json={"legal_entity_id": "entity-2"})
    assert new_accept.status_code == 200
    assert new_accept.json()["legal_entity_id"] == "entity-2"


def test_reissue_after_bind_conflicts(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    manager = TestClient(build_isolated_app(conn, actor("u1"), notification_provider=FakeNotificationProvider()))
    token = _create_seller_invitation(conn, manager, tx_id)
    invitation_id = conn.execute(
        "SELECT id FROM transaction_invitations WHERE transaction_id = ?", (tx_id,)
    ).fetchone()["id"]
    create_test_user(conn, email_normalized="party@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2")
    TestClient(build_isolated_app(conn, actor("u2", "entity-2"))).post(
        f"/api/invitations/{token}/accept", json={"legal_entity_id": "entity-2"}
    )

    # Seller rolü bağlandıktan sonra reissue reddedilir (role already bound).
    resp = manager.post(f"/api/transactions/{tx_id}/invitations/{invitation_id}/reissue")
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVITATION_ROLE_ALREADY_BOUND"


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
