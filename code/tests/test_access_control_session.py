"""`access_control.py::get_current_actor`'ın Faz 3A session-actor genişletmesi.

`test_access_control_contract.py` Plan 02 freeze'ini test eder ve DEĞİŞTİRİLMEZ;
bu dosya yalnızca yeni session-actor davranışını (X-Acting-Entity-ID, öncelik
sırası, request_id akışı) kapsar.
"""

from __future__ import annotations

import dataclasses

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.services import auth as auth_service
from backend.app.services import identity as identity_service
from backend.app.services.access_control import ActorContext, get_current_actor
from tests._identity_support import identity_keys  # noqa: F401


def _build_probe_app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    def whoami(actor: ActorContext = Depends(get_current_actor)):
        return dataclasses.asdict(actor)

    return app


def _issue_session_cookie(client: TestClient, *, user_id: str) -> None:
    conn = connect()
    try:
        issued = auth_service.create_session(conn, user_id=user_id, settings=Settings())
        conn.commit()
    finally:
        conn.close()
    client.cookies.set(auth_service.SESSION_COOKIE_NAME, issued.raw_token)


def test_session_actor_takes_priority_over_capability_token() -> None:
    conn = connect()
    init_db(conn)
    user_id = auth_service.register_user(
        conn, email="prio@example.com", password="password123", first_name="A", last_name="B"
    )
    conn.commit()
    conn.close()

    client = TestClient(_build_probe_app())
    _issue_session_cookie(client, user_id=user_id)

    response = client.get("/whoami", params={"token": "legacy-token-value"})
    body = response.json()
    assert body["actor_type"] == "user"
    assert body["auth_method"] == "session"
    assert body["user_id"] == user_id


def test_no_session_cookie_falls_back_to_legacy_capability() -> None:
    conn = connect()
    init_db(conn)
    conn.close()

    client = TestClient(_build_probe_app())
    response = client.get("/whoami", params={"token": "legacy-token-value"})
    body = response.json()
    assert body["actor_type"] == "legacy_capability"
    assert body["auth_method"] == "legacy_capability"


def test_no_session_and_no_token_is_anonymous() -> None:
    conn = connect()
    init_db(conn)
    conn.close()

    client = TestClient(_build_probe_app())
    response = client.get("/whoami")
    body = response.json()
    assert body["actor_type"] == "anonymous"
    assert body["auth_method"] == "none"


def test_invalid_session_cookie_falls_back_to_anonymous() -> None:
    conn = connect()
    init_db(conn)
    conn.close()

    client = TestClient(_build_probe_app())
    client.cookies.set(auth_service.SESSION_COOKIE_NAME, "not-a-real-session-token")
    response = client.get("/whoami")
    assert response.json()["actor_type"] == "anonymous"


def test_acting_entity_header_fills_only_with_verified_active_membership(identity_keys) -> None:
    conn = connect()
    init_db(conn)
    user_id = auth_service.register_user(
        conn, email="entityowner@example.com", password="password123", first_name="A", last_name="B"
    )
    entity_id = identity_service.create_entity(
        conn,
        entity_type="company",
        legal_name="ABC",
        tax_identifier_type="vkn",
        raw_tax_identifier="1234567890",
        tax_office=None,
        address_json=None,
        created_by_user_id=user_id,
        settings=Settings.from_env(),
    )
    conn.commit()
    conn.close()

    client = TestClient(_build_probe_app())
    _issue_session_cookie(client, user_id=user_id)

    verified = client.get("/whoami", headers={"X-Acting-Entity-ID": entity_id})
    assert verified.json()["acting_entity_id"] == entity_id

    unverified = client.get("/whoami", headers={"X-Acting-Entity-ID": "not-a-real-entity"})
    assert unverified.json()["acting_entity_id"] is None


def test_request_id_propagates_into_session_actor() -> None:
    conn = connect()
    init_db(conn)
    user_id = auth_service.register_user(
        conn, email="reqid@example.com", password="password123", first_name="A", last_name="B"
    )
    conn.commit()
    conn.close()

    app = FastAPI()

    @app.middleware("http")
    async def _inject_request_id(request, call_next):
        request.state.request_id = "probe-request-id"
        return await call_next(request)

    @app.get("/whoami")
    def whoami(actor: ActorContext = Depends(get_current_actor)):
        return dataclasses.asdict(actor)

    client = TestClient(app)
    _issue_session_cookie(client, user_id=user_id)

    response = client.get("/whoami")
    assert response.json()["request_id"] == "probe-request-id"
