"""`services/invitations.py` — create/preview/revoke lifecycle testleri
(`accept` frozen `ParticipantService.accept_invitation`de test edilir, bkz.
`test_participant_service.py`)."""

from __future__ import annotations

import pytest

from backend.app.services import invitations as svc
from backend.app.services import participants as participants_svc
from backend.app.services.access_control import ActorContext
from backend.app.services.notifications import FakeNotificationProvider
from participants_fixtures import create_test_transaction, make_participants_db


@pytest.fixture()
def conn():
    connection = make_participants_db()
    try:
        yield connection
    finally:
        connection.close()


def actor(user_id="u1") -> ActorContext:
    return ActorContext(actor_type="legacy_capability", user_id=user_id, request_id="req-1")


ANONYMOUS = ActorContext(actor_type="anonymous")


def _link_builder(raw_token: str) -> str:
    return f"/api/invitations/{raw_token}/accept"


# --- create_invitation ----------------------------------------------------------


def test_create_invitation_requires_authenticated_actor(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()

    with pytest.raises(svc.InvitationAuthorizationError):
        svc.create_invitation(
            conn, tx_id, "seller", "party@example.com", ANONYMOUS, provider,
            invite_link_builder=_link_builder,
        )


def test_create_invitation_requires_manager_role(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()

    with pytest.raises(svc.InvitationAuthorizationError):
        svc.create_invitation(
            conn, tx_id, "seller", "party@example.com", actor("someone-else"), provider,
            invite_link_builder=_link_builder,
        )


def test_create_invitation_succeeds_for_manager_and_hashes_token(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()

    created = svc.create_invitation(
        conn, tx_id, "seller", "PARTY@Example.com", actor("u1"), provider,
        invite_link_builder=_link_builder,
    )

    assert created.notification_delivered is True
    assert len(provider.sent) == 1
    assert provider.sent[0].recipient == "PARTY@Example.com"

    row = conn.execute(
        "SELECT * FROM transaction_invitations WHERE id = ?", (created.invitation_id,)
    ).fetchone()
    assert row["token_hash"] != created.raw_token
    assert len(row["token_hash"]) == 64  # sha256 hex


def test_create_invitation_raw_token_never_persisted(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()

    created = svc.create_invitation(
        conn, tx_id, "seller", "party@example.com", actor("u1"), provider,
        invite_link_builder=_link_builder,
    )

    row = conn.execute(
        "SELECT * FROM transaction_invitations WHERE id = ?", (created.invitation_id,)
    ).fetchone()
    for value in dict(row).values():
        assert created.raw_token not in str(value)


def test_create_invitation_writes_audit_row(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()

    svc.create_invitation(
        conn, tx_id, "seller", "party@example.com", actor("u1"), provider,
        invite_link_builder=_link_builder,
    )
    audit_row = conn.execute(
        "SELECT * FROM audit_events WHERE action = 'invitation.created'"
    ).fetchone()
    assert audit_row is not None
    assert audit_row["actor_user_id"] == "u1"


def test_create_invitation_survives_notification_delivery_failure(conn) -> None:
    """Provider hatası business mutation'ı belirsiz bırakmaz: invitation satırı
    yine de tutarlı bir `pending` satır olarak kalır (yalnız bildirim işaretlenir)."""
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider(fail_next=True)

    created = svc.create_invitation(
        conn, tx_id, "seller", "party@example.com", actor("u1"), provider,
        invite_link_builder=_link_builder,
    )

    assert created.notification_delivered is False
    row = conn.execute(
        "SELECT status FROM transaction_invitations WHERE id = ?", (created.invitation_id,)
    ).fetchone()
    assert row["status"] == "pending"


# --- preview_invitation -----------------------------------------------------------


def test_preview_invitation_returns_role_and_reference_without_pii(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    created = svc.create_invitation(
        conn, tx_id, "seller", "party@example.com", actor("u1"), provider,
        invite_link_builder=_link_builder,
    )

    preview = svc.preview_invitation(conn, created.raw_token)

    assert preview.participant_role.value == "seller"
    assert "party@example.com" not in preview.model_dump_json()
    assert "entity-1" not in preview.model_dump_json()


def test_preview_invitation_does_not_write_to_db(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    created = svc.create_invitation(
        conn, tx_id, "seller", "party@example.com", actor("u1"), provider,
        invite_link_builder=_link_builder,
    )
    conn.commit()

    before = dict(conn.execute(
        "SELECT status, accepted_at, revoked_at FROM transaction_invitations WHERE id = ?",
        (created.invitation_id,),
    ).fetchone())

    svc.preview_invitation(conn, created.raw_token)
    svc.preview_invitation(conn, created.raw_token)

    after = dict(conn.execute(
        "SELECT status, accepted_at, revoked_at FROM transaction_invitations WHERE id = ?",
        (created.invitation_id,),
    ).fetchone())
    assert before == after == {"status": "pending", "accepted_at": None, "revoked_at": None}


def test_preview_invitation_unknown_token_not_found(conn) -> None:
    with pytest.raises(svc.InvitationNotFoundError):
        svc.preview_invitation(conn, "unknown-token")


def test_preview_invitation_revoked_not_found(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    created = svc.create_invitation(
        conn, tx_id, "seller", "party@example.com", actor("u1"), provider,
        invite_link_builder=_link_builder,
    )
    svc.revoke_invitation(conn, tx_id, created.invitation_id, actor("u1"))

    with pytest.raises(svc.InvitationNotFoundError):
        svc.preview_invitation(conn, created.raw_token)


# --- revoke_invitation -----------------------------------------------------------


def test_revoke_invitation_by_manager_succeeds(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    created = svc.create_invitation(
        conn, tx_id, "seller", "party@example.com", actor("u1"), provider,
        invite_link_builder=_link_builder,
    )

    svc.revoke_invitation(conn, tx_id, created.invitation_id, actor("u1"))

    row = conn.execute(
        "SELECT status FROM transaction_invitations WHERE id = ?", (created.invitation_id,)
    ).fetchone()
    assert row["status"] == "revoked"


def test_revoke_invitation_by_unrelated_actor_is_forbidden(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    created = svc.create_invitation(
        conn, tx_id, "seller", "party@example.com", actor("u1"), provider,
        invite_link_builder=_link_builder,
    )

    with pytest.raises(svc.InvitationAuthorizationError):
        svc.revoke_invitation(conn, tx_id, created.invitation_id, actor("unrelated-user"))


def test_revoke_invitation_twice_raises_not_revocable(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    provider = FakeNotificationProvider()
    created = svc.create_invitation(
        conn, tx_id, "seller", "party@example.com", actor("u1"), provider,
        invite_link_builder=_link_builder,
    )
    svc.revoke_invitation(conn, tx_id, created.invitation_id, actor("u1"))

    with pytest.raises(svc.InvitationNotRevocableError):
        svc.revoke_invitation(conn, tx_id, created.invitation_id, actor("u1"))


def test_revoke_invitation_unknown_id_not_found(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    with pytest.raises(svc.InvitationNotFoundError):
        svc.revoke_invitation(conn, tx_id, "does-not-exist", actor("u1"))
