"""Payment operations router erişim ve projection testleri."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.main import app
from backend.app.repositories import participants as participants_repo
from backend.app.services.access_control import ActorContext, get_current_actor
from backend.app.services.payments import funding_coordinator

from test_plan06a_persistence import _seed_complete_package


def _actor(user_id: str, entity_id: str = "entity") -> ActorContext:
    return ActorContext(
        actor_type="user",
        user_id=user_id,
        acting_entity_id=entity_id,
        auth_method="session",
        request_id="req-api-07",
    )


def test_manager_reconcile_and_trace_are_scoped(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "payment-ops-api.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    conn = connect(Settings(db_path=db_path))
    init_db(conn)
    transaction_id, package_id = _seed_complete_package(conn)
    participants_repo.create_assignment(
        conn,
        transaction_id=transaction_id,
        participant_id=None,
        user_id="manager-api-07",
        legal_entity_id="entity",
        role="manager",
    )
    funding_coordinator.ensure_pool_funded(
        conn,
        transaction_id,
        package_id,
        _actor("manager-api-07"),
    )
    conn.commit()
    conn.close()

    app.dependency_overrides[get_current_actor] = lambda: _actor("manager-api-07")
    try:
        with TestClient(app) as client:
            trace = client.get(f"/api/transactions/{transaction_id}/payment-trace")
            assert trace.status_code == 200
            assert trace.json()["operations"]
            assert "Password" not in trace.text
            reconcile = client.post(
                f"/api/transactions/{transaction_id}/payments/reconcile"
            )
            assert reconcile.status_code == 200
            assert reconcile.json()["results"] == []
    finally:
        app.dependency_overrides.clear()
