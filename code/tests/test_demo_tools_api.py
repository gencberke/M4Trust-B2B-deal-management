"""Plan 14 / P2 — gizli demo router (`routers/demo_tools.py`) + flag/tripwire.

Flag kapalıyken uçlar 404 + OpenAPI'de yok (frontend gate'i); flag açıkken
authenticated session ile çalışır; secure-cookie tripwire mount'u reddeder.
`create_scenario`/`advance` seed'li taraflarla gerçek servisleri sürer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.main import create_app
from reviews_fixtures import create_real_session, create_real_user


def _entity(conn, entity_id: str, legal_name: str, user_id: str) -> None:
    conn.execute(
        "INSERT INTO legal_entities (id, entity_type, legal_name, tax_identifier_type, "
        "tax_identifier_ciphertext, tax_identifier_lookup_hmac, tax_identifier_last4, "
        "verification_status, created_by_user_id, created_at, updated_at) "
        "VALUES (?, 'company', ?, 'vkn', 'cipher', ?, '1234', 'self_declared', ?, 'now', 'now')",
        (entity_id, legal_name, entity_id, user_id),
    )


def _membership(conn, user_id: str, entity_id: str) -> None:
    conn.execute(
        "INSERT INTO memberships (id, user_id, legal_entity_id, role, status, created_at) "
        "VALUES (?, ?, ?, 'owner', 'active', 'now')",
        (f"m-{user_id}-{entity_id}", user_id, entity_id),
    )


def _seed_demo_identities(conn):
    """Berke/Yusuf + ABC/XYZ (resolve_seeded_demo_parties ile eşleşen kimlikler)."""
    create_real_user(conn, email_normalized="berke@m4trust.demo", user_id="u-berke")
    create_real_user(conn, email_normalized="yusuf@m4trust.demo", user_id="u-yusuf")
    _entity(conn, "e-abc", "ABC Sanayi ve Ticaret A.Ş.", "u-berke")
    _entity(conn, "e-xyz", "XYZ Lojistik Ltd. Şti.", "u-yusuf")
    _membership(conn, "u-berke", "e-abc")
    _membership(conn, "u-yusuf", "e-xyz")


def _prepare_db():
    conn = connect(Settings.from_env())
    init_db(conn)
    _seed_demo_identities(conn)
    session = create_real_session(conn, user_id="u-berke")
    conn.commit()
    conn.close()
    return session


def test_demo_status_404_and_absent_from_openapi_when_flag_off(monkeypatch) -> None:
    monkeypatch.delenv("DEMO_TOOLS_ENABLED", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/api/demo/status").status_code == 404
        paths = client.get("/openapi.json").json()["paths"]
        assert not any(path.startswith("/api/demo") for path in paths)


def test_demo_status_200_when_flag_on(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_TOOLS_ENABLED", "true")
    session = _prepare_db()
    with TestClient(create_app()) as client:
        client.cookies.set("m4t_session", session.raw_token)
        resp = client.get("/api/demo/status")
        assert resp.status_code == 200
        assert resp.json() == {"demo_tools_enabled": True}
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/demo/status" in paths


def test_demo_status_requires_auth_when_flag_on(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_TOOLS_ENABLED", "true")
    _prepare_db()
    with TestClient(create_app()) as client:
        assert client.get("/api/demo/status").status_code == 401


def test_secure_cookie_tripwire_rejects_mount(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_TOOLS_ENABLED", "true")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    with TestClient(create_app()) as client:
        # Secure cookie = prod proxy işareti → mount reddedilir → uç yok.
        assert client.get("/api/demo/status").status_code == 404


def test_create_scenario_endpoint_reaches_active(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_TOOLS_ENABLED", "true")
    session = _prepare_db()
    with TestClient(create_app()) as client:
        client.cookies.set("m4t_session", session.raw_token)
        resp = client.post(
            "/api/demo/scenarios",
            json={"scenario": "active", "transaction_id": "demo-api-active", "title": "API demo"},
            headers={"X-CSRF-Token": session.raw_csrf_token, "X-Acting-Entity-ID": "e-abc"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == "active"


def test_advance_unknown_target_returns_400(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_TOOLS_ENABLED", "true")
    session = _prepare_db()
    with TestClient(create_app()) as client:
        client.cookies.set("m4t_session", session.raw_token)
        # Önce taze bir işlem üret.
        client.post(
            "/api/demo/scenarios",
            json={"scenario": "awaiting_ratification", "transaction_id": "demo-api-x", "title": "x"},
            headers={"X-CSRF-Token": session.raw_csrf_token, "X-Acting-Entity-ID": "e-abc"},
        )
        resp = client.post(
            "/api/demo/transactions/demo-api-x/advance",
            json={"target_state": "nonsense"},
            headers={"X-CSRF-Token": session.raw_csrf_token, "X-Acting-Entity-ID": "e-abc"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "DEMO_ADVANCE_FAILED"
