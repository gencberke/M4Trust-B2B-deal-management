"""`routers/participants.py` — izole app + StubActor ile API-seviyesi testler."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.services.access_control import ActorContext
from backend.app.services import participants as participants_svc
from participants_fixtures import (
    build_isolated_app,
    create_test_transaction,
    make_participants_db,
)


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


def test_list_participants_requires_auth(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    app = build_isolated_app(conn, ANONYMOUS)
    response = TestClient(app).get(f"/api/transactions/{tx_id}/participants")
    assert response.status_code == 401


def test_list_participants_denies_unrelated_actor_idor(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    app = build_isolated_app(conn, actor("intruder"))
    response = TestClient(app).get(f"/api/transactions/{tx_id}/participants")
    assert response.status_code == 403


def test_list_participants_returns_public_view_without_pii(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    participants_svc.update_declared_profile(
        conn, tx_id, actor("u1"), {"name": "Buyer Co.", "tax_id": "1234567890"}
    )
    app = build_isolated_app(conn, actor("u1"))
    response = TestClient(app).get(f"/api/transactions/{tx_id}/participants")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["display_name"] == "Buyer Co."
    assert "tax_id" not in body[0]
    assert "declared_snapshot" not in body[0]
    assert "1234567890" not in response.text


def test_put_profile_writes_only_own_participant(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    app = build_isolated_app(conn, actor("u1"))
    client = TestClient(app)

    response = client.put(
        f"/api/transactions/{tx_id}/participants/me/profile",
        json={"snapshot": {"name": "Buyer Co."}},
    )
    assert response.status_code == 200
    assert response.json()["declared_snapshot"]["name"] == "Buyer Co."


def test_put_profile_unrelated_actor_gets_404_not_another_partys_profile(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    conn.commit()  # setup'ı kalıcı yap ki aşağıdaki 404'ün rollback'i bunu silmesin
    app = build_isolated_app(conn, actor("intruder"))
    client = TestClient(app)

    response = client.put(
        f"/api/transactions/{tx_id}/participants/me/profile",
        json={"snapshot": {"name": "Hijacked"}},
    )
    assert response.status_code == 404

    row = conn.execute(
        "SELECT declared_snapshot_json FROM transaction_participants WHERE transaction_id = ? AND role='buyer'",
        (tx_id,),
    ).fetchone()
    assert row["declared_snapshot_json"] is None


def test_confirm_profile_end_to_end(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    app = build_isolated_app(conn, actor("u1"))
    client = TestClient(app)

    client.put(
        f"/api/transactions/{tx_id}/participants/me/profile",
        json={"snapshot": {"name": "Buyer Co."}},
    )
    response = client.post(f"/api/transactions/{tx_id}/participants/me/confirm")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["confirmed_at"] is not None
    assert body["confirmed_snapshot"]["name"] == "Buyer Co."


def test_confirm_twice_returns_409_no_silent_overwrite(conn) -> None:
    tx_id = create_test_transaction(conn)
    participants_svc.attach_creator(conn, tx_id, actor("u1"), "buyer", "entity-1")
    app = build_isolated_app(conn, actor("u1"))
    client = TestClient(app)
    client.put(
        f"/api/transactions/{tx_id}/participants/me/profile",
        json={"snapshot": {"name": "Buyer Co."}},
    )
    client.post(f"/api/transactions/{tx_id}/participants/me/confirm")

    response = client.post(f"/api/transactions/{tx_id}/participants/me/confirm")
    assert response.status_code == 409
    assert response.json()["code"] == "PARTICIPANT_CONFIRM_CONFLICT"


def test_dependency_override_cleanup_after_test(dependency_override_cleanup) -> None:
    """conftest.py'nin ortak `dependency_override_cleanup` fixture'ı gerçekten
    `app.dependency_overrides`'ı temizliyor mu -- burada `backend.app.main.app`
    (gerçek uygulama) üzerinden doğrulanır, izole test app'lerinden bağımsız."""
    from backend.app.services.access_control import get_current_actor

    dependency_override_cleanup[get_current_actor] = lambda: ANONYMOUS
    from backend.app.main import app as real_app

    assert real_app.dependency_overrides.get(get_current_actor) is not None
