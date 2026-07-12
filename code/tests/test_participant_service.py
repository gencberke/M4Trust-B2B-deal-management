"""Frozen `ParticipantService` (v2 §8.1) davranış testleri: `attach_creator`,
`create_counterparty_placeholder`, `accept_invitation` + profile/confirm
yardımcıları. 3A henüz merge olmadığı için `users`/`memberships` test-özel
stub tablolarla (`participants_fixtures.py`) simüle edilir.
"""

from __future__ import annotations

import hashlib

import pytest

from backend.app.repositories import invitations as invitations_repo
from backend.app.services import participants as svc
from backend.app.services.access_control import ActorContext
from participants_fixtures import (
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


def actor(user_id="u1", entity_id="entity-1", request_id="req-1") -> ActorContext:
    return ActorContext(
        actor_type="user",
        user_id=user_id,
        acting_entity_id=entity_id,
        request_id=request_id,
    )


ANONYMOUS = ActorContext(actor_type="anonymous")


# --- attach_creator -----------------------------------------------------------


def test_attach_creator_requires_authenticated_actor(conn) -> None:
    tx_id = create_test_transaction(conn)
    with pytest.raises(svc.ParticipantAuthorizationError):
        svc.attach_creator(conn, tx_id, ANONYMOUS, "buyer", "entity-1")


def test_attach_creator_creates_participant_and_manager_assignment(conn) -> None:
    tx_id = create_test_transaction(conn)
    participant = svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")

    assert participant.role.value == "buyer"
    assert participant.legal_entity_id == "entity-1"
    assert participant.status.value == "ready"

    assignment = conn.execute(
        "SELECT * FROM transaction_assignments WHERE transaction_id = ? AND user_id = 'u1'",
        (tx_id,),
    ).fetchone()
    assert assignment["role"] == "manager"
    assert assignment["participant_id"] == participant.id


def test_attach_creator_is_idempotent_on_repeat_call(conn) -> None:
    tx_id = create_test_transaction(conn)
    first = svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    second = svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")

    assert first.id == second.id
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM transaction_participants WHERE transaction_id = ?", (tx_id,)
    ).fetchone()["n"]
    assert count == 1
    assignment_count = conn.execute(
        "SELECT COUNT(*) AS n FROM transaction_assignments WHERE transaction_id = ? AND user_id = 'u1'",
        (tx_id,),
    ).fetchone()["n"]
    assert assignment_count == 1


def test_attach_creator_rejects_same_entity_as_existing_counterparty(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.create_counterparty_placeholder(conn, tx_id, "seller", None)
    conn.execute(
        "UPDATE transaction_participants SET legal_entity_id = 'entity-1' "
        "WHERE transaction_id = ? AND role = 'seller'",
        (tx_id,),
    )

    with pytest.raises(svc.ParticipantConflictError):
        svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")


def test_attach_creator_conflicts_if_role_owned_by_different_entity(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")

    with pytest.raises(svc.ParticipantConflictError):
        svc.attach_creator(conn, tx_id, actor("u2", "entity-2"), "buyer", "entity-2")


def test_attach_creator_writes_audit_row(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")

    audit_row = conn.execute(
        "SELECT * FROM audit_events WHERE action = 'participant.creator_attached'"
    ).fetchone()
    assert audit_row is not None
    assert audit_row["actor_user_id"] == "u1"
    assert audit_row["transaction_id"] == tx_id


# --- create_counterparty_placeholder -------------------------------------------


def test_create_counterparty_placeholder_stores_extracted_snapshot_only(conn) -> None:
    tx_id = create_test_transaction(conn)
    snapshot = {"name": "ACME A.Ş."}
    participant = svc.create_counterparty_placeholder(conn, tx_id, "seller", snapshot)

    assert participant.status.value == "invited"
    assert participant.extracted_snapshot.name == "ACME A.Ş."
    assert participant.declared_snapshot is None
    assert participant.confirmed_snapshot is None


def test_create_counterparty_placeholder_is_idempotent(conn) -> None:
    tx_id = create_test_transaction(conn)
    first = svc.create_counterparty_placeholder(conn, tx_id, "seller", {"name": "A"})
    second = svc.create_counterparty_placeholder(conn, tx_id, "seller", {"name": "B (should be ignored)"})

    assert first.id == second.id
    assert second.extracted_snapshot.name == "A"


# --- accept_invitation ---------------------------------------------------------


def _make_pending_invitation(conn, tx_id, *, role="seller", email="party@example.com", creator="u1", raw_token="raw-token-abc"):
    svc.create_counterparty_placeholder(conn, tx_id, role, None)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    from datetime import datetime, timedelta, timezone

    invitations_repo.create_invitation(
        conn,
        transaction_id=tx_id,
        participant_role=role,
        invited_email_normalized=email,
        token_hash=token_hash,
        expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        created_by_user_id=creator,
    )
    return raw_token


def test_accept_invitation_requires_authenticated_actor(conn) -> None:
    tx_id = create_test_transaction(conn)
    raw_token = _make_pending_invitation(conn, tx_id)
    with pytest.raises(svc.ParticipantAuthorizationError):
        svc.accept_invitation(conn, raw_token, ANONYMOUS, "entity-2")


def test_accept_invitation_unknown_token_raises_not_found(conn) -> None:
    tx_id = create_test_transaction(conn)
    _make_pending_invitation(conn, tx_id)
    create_test_user(conn, email_normalized="party@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2")

    with pytest.raises(svc.InvitationNotFoundError):
        svc.accept_invitation(conn, "totally-wrong-token", actor("u2", "entity-2"), "entity-2")


def test_accept_invitation_wrong_email_raises_mismatch(conn) -> None:
    tx_id = create_test_transaction(conn)
    raw_token = _make_pending_invitation(conn, tx_id, email="expected@example.com")
    create_test_user(conn, email_normalized="different@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2")

    with pytest.raises(svc.InvitationEmailMismatchError):
        svc.accept_invitation(conn, raw_token, actor("u2", "entity-2"), "entity-2")


def test_accept_invitation_expired_raises_not_acceptable(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.create_counterparty_placeholder(conn, tx_id, "seller", None)
    token_hash = hashlib.sha256(b"raw-token-expired").hexdigest()
    from datetime import datetime, timedelta, timezone

    invitations_repo.create_invitation(
        conn,
        transaction_id=tx_id,
        participant_role="seller",
        invited_email_normalized="party@example.com",
        token_hash=token_hash,
        expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        created_by_user_id="u1",
    )
    create_test_user(conn, email_normalized="party@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2")

    with pytest.raises(svc.InvitationNotAcceptableError):
        svc.accept_invitation(conn, "raw-token-expired", actor("u2", "entity-2"), "entity-2")


def test_accept_invitation_reused_raises_not_acceptable(conn) -> None:
    tx_id = create_test_transaction(conn)
    raw_token = _make_pending_invitation(conn, tx_id)
    create_test_user(conn, email_normalized="party@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2")

    svc.accept_invitation(conn, raw_token, actor("u2", "entity-2"), "entity-2")

    with pytest.raises(svc.InvitationNotAcceptableError):
        svc.accept_invitation(conn, raw_token, actor("u2", "entity-2"), "entity-2")


def test_accept_invitation_revoked_raises_not_acceptable(conn) -> None:
    tx_id = create_test_transaction(conn)
    raw_token = _make_pending_invitation(conn, tx_id)
    create_test_user(conn, email_normalized="party@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2")

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    invitation = invitations_repo.get_invitation_by_token_hash(conn, token_hash)
    invitations_repo.mark_revoked(conn, invitation["id"])

    with pytest.raises(svc.InvitationNotAcceptableError):
        svc.accept_invitation(conn, raw_token, actor("u2", "entity-2"), "entity-2")


def test_accept_invitation_creator_cannot_accept_own_invitation(conn) -> None:
    tx_id = create_test_transaction(conn)
    raw_token = _make_pending_invitation(conn, tx_id, creator="u1", email="party@example.com")
    create_test_user(conn, email_normalized="party@example.com", user_id="u1")
    create_test_membership(conn, user_id="u1", legal_entity_id="entity-2")

    with pytest.raises(svc.ParticipantConflictError):
        svc.accept_invitation(conn, raw_token, actor("u1", "entity-2"), "entity-2")


def test_accept_invitation_same_entity_as_other_role_raises_conflict(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.attach_creator(conn, tx_id, actor("u1", "entity-shared"), "buyer", "entity-shared")
    raw_token = _make_pending_invitation(conn, tx_id, email="party@example.com")
    create_test_user(conn, email_normalized="party@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-shared")

    with pytest.raises(svc.ParticipantConflictError):
        svc.accept_invitation(conn, raw_token, actor("u2", "entity-shared"), "entity-shared")


def test_accept_invitation_inactive_membership_raises_authorization_error(conn) -> None:
    tx_id = create_test_transaction(conn)
    raw_token = _make_pending_invitation(conn, tx_id, email="party@example.com")
    create_test_user(conn, email_normalized="party@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2", status="revoked")

    with pytest.raises(svc.ParticipantAuthorizationError):
        svc.accept_invitation(conn, raw_token, actor("u2", "entity-2"), "entity-2")


def test_accept_invitation_success_links_participant_and_creates_approver_assignment(conn) -> None:
    tx_id = create_test_transaction(conn)
    raw_token = _make_pending_invitation(conn, tx_id, email="party@example.com")
    create_test_user(conn, email_normalized="party@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2")

    participant = svc.accept_invitation(conn, raw_token, actor("u2", "entity-2"), "entity-2")

    assert participant.role.value == "seller"
    assert participant.legal_entity_id == "entity-2"
    assert participant.status.value == "ready"

    assignment = conn.execute(
        "SELECT * FROM transaction_assignments WHERE transaction_id = ? AND user_id = 'u2'",
        (tx_id,),
    ).fetchone()
    assert assignment["role"] == "approver"

    invitation = conn.execute(
        "SELECT * FROM transaction_invitations WHERE transaction_id = ?", (tx_id,)
    ).fetchone()
    assert invitation["status"] == "accepted"
    assert invitation["accepted_by_user_id"] == "u2"

    audit_row = conn.execute(
        "SELECT * FROM audit_events WHERE action = 'invitation.accepted'"
    ).fetchone()
    assert audit_row is not None
    assert audit_row["transaction_id"] == tx_id


def test_accept_invitation_concurrent_double_accept_only_one_succeeds(conn) -> None:
    """Gerçek thread'ler yerine tek connection'da sıralı iki çağrı ile aynı
    'yalnız pending iken kabul et' compare-and-swap garantisini doğrular --
    ikinci çağrı DB'de hâlâ `status='pending'` bulsaydı da bulmaz, çünkü ilk
    çağrı zaten commit'e gitmeden aynı transaction'da satırı 'accepted'
    yapmış olur (UPDATE ... WHERE status='pending' rowcount=0)."""
    tx_id = create_test_transaction(conn)
    raw_token = _make_pending_invitation(conn, tx_id, email="party@example.com")
    create_test_user(conn, email_normalized="party@example.com", user_id="u2")
    create_test_membership(conn, user_id="u2", legal_entity_id="entity-2")

    svc.accept_invitation(conn, raw_token, actor("u2", "entity-2"), "entity-2")
    with pytest.raises(svc.InvitationNotAcceptableError):
        svc.accept_invitation(conn, raw_token, actor("u2", "entity-2"), "entity-2")


def test_two_invitations_cannot_overwrite_bound_participant_or_leave_stale_assignment(conn) -> None:
    """Legacy/yarış kaynaklı iki pending satır bulunsa bile ilk accept rolü
    atomik bağlar, diğerini revoke eder ve ikinci entity ownership'i ezemez."""
    tx_id = create_test_transaction(conn)
    svc.create_counterparty_placeholder(conn, tx_id, "seller", None)
    from datetime import datetime, timedelta, timezone

    expires_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    tokens = (("token-a", "a@example.com", "u2", "entity-a"),
              ("token-b", "b@example.com", "u3", "entity-b"))
    for raw_token, email, user_id, entity_id in tokens:
        invitations_repo.create_invitation(
            conn,
            transaction_id=tx_id,
            participant_role="seller",
            invited_email_normalized=email,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=expires_at,
            created_by_user_id="u1",
        )
        create_test_user(conn, email_normalized=email, user_id=user_id)
        create_test_membership(conn, user_id=user_id, legal_entity_id=entity_id)

    accepted = svc.accept_invitation(conn, "token-a", actor("u2", "entity-a"), "entity-a")
    assert accepted.legal_entity_id == "entity-a"

    with pytest.raises(svc.InvitationNotAcceptableError):
        svc.accept_invitation(conn, "token-b", actor("u3", "entity-b"), "entity-b")

    participant = conn.execute(
        "SELECT legal_entity_id, status, confirmed_at FROM transaction_participants "
        "WHERE transaction_id = ? AND role = 'seller'",
        (tx_id,),
    ).fetchone()
    assert dict(participant) == {
        "legal_entity_id": "entity-a",
        "status": "ready",
        "confirmed_at": None,
    }
    assignments = conn.execute(
        "SELECT user_id, legal_entity_id FROM transaction_assignments "
        "WHERE transaction_id = ? AND role = 'approver'",
        (tx_id,),
    ).fetchall()
    assert [dict(row) for row in assignments] == [
        {"user_id": "u2", "legal_entity_id": "entity-a"}
    ]


# --- profile / confirm ---------------------------------------------------------


def test_update_declared_profile_only_writes_own_participant(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")

    updated = svc.update_declared_profile(
        conn, tx_id, actor("u1"), {"name": "Buyer Co."}
    )
    assert updated.declared_snapshot.name == "Buyer Co."
    assert updated.role.value == "buyer"


def test_update_declared_profile_rejects_actor_without_participant(conn) -> None:
    tx_id = create_test_transaction(conn)
    with pytest.raises(svc.ParticipantNotFoundError):
        svc.update_declared_profile(conn, tx_id, actor("unrelated-user"), {"name": "X"})


def test_profile_mutations_require_exact_acting_entity(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")

    with pytest.raises(svc.ParticipantAuthorizationError):
        svc.update_declared_profile(
            conn, tx_id, actor("u1", "entity-other"), {"name": "Hijacked"}
        )
    with pytest.raises(svc.ParticipantAuthorizationError):
        svc.confirm_my_profile(conn, tx_id, actor("u1", entity_id=None))


def test_confirm_profile_produces_immutable_snapshot_and_confirmed_at(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    svc.update_declared_profile(conn, tx_id, actor("u1"), {"name": "Buyer Co."})

    confirmed = svc.confirm_my_profile(conn, tx_id, actor("u1"))

    assert confirmed.status.value == "confirmed"
    assert confirmed.confirmed_at is not None
    assert confirmed.confirmed_snapshot.name == "Buyer Co."


def test_confirmed_profile_cannot_be_silently_overwritten_by_update(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    svc.update_declared_profile(conn, tx_id, actor("u1"), {"name": "Buyer Co."})
    svc.confirm_my_profile(conn, tx_id, actor("u1"))

    with pytest.raises(svc.ParticipantConflictError):
        svc.update_declared_profile(conn, tx_id, actor("u1"), {"name": "Sneaky Rename"})

    row = conn.execute(
        "SELECT confirmed_snapshot_json FROM transaction_participants WHERE transaction_id = ? AND role = 'buyer'",
        (tx_id,),
    ).fetchone()
    assert "Buyer Co." in row["confirmed_snapshot_json"]
    assert "Sneaky Rename" not in row["confirmed_snapshot_json"]


def test_confirm_twice_raises_conflict_no_silent_overwrite(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    svc.update_declared_profile(conn, tx_id, actor("u1"), {"name": "Buyer Co."})
    svc.confirm_my_profile(conn, tx_id, actor("u1"))

    with pytest.raises(svc.ParticipantConflictError):
        svc.confirm_my_profile(conn, tx_id, actor("u1"))


def test_confirm_without_declared_profile_raises_conflict(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")

    with pytest.raises(svc.ParticipantConflictError):
        svc.confirm_my_profile(conn, tx_id, actor("u1"))


# --- access helpers (IDOR yapı taşı) --------------------------------------------


def test_unrelated_actor_has_no_transaction_access(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")

    assert svc.has_transaction_access(conn, tx_id, "u1") is True
    assert svc.has_transaction_access(conn, tx_id, "totally-unrelated-user") is False


def test_unrelated_actor_has_no_participant_for_transaction(conn) -> None:
    tx_id = create_test_transaction(conn)
    svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")

    assert svc.get_my_participant(conn, tx_id, "totally-unrelated-user") is None
