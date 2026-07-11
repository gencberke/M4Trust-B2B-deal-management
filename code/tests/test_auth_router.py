"""`routers/auth.py` — isolated FastAPI app üzerinden HTTP-seviyesi testler.

`main.py`'ye kayıt yapılmaz (Plan 03 integration checkpoint'i bekler); bu
dosya kendi izole app'ini kurar ve `DB_PATH` izolasyonunu
`tests/conftest.py::isolated_db` (autouse) sağlar.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.db import connect, init_db
from backend.app.routers.auth import router as auth_router
from backend.app.services.access_control import ActorContext, get_current_actor
from tests._identity_support import build_app_with_routers


def _client() -> TestClient:
    conn = connect()
    init_db(conn)
    conn.close()
    app = build_app_with_routers(auth_router)
    return TestClient(app)


def _register_and_login(client: TestClient, *, email: str = "a@b.com", password: str = "password123") -> None:
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "first_name": "A", "last_name": "B"},
    )
    assert r.status_code == 201
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200


def test_register_returns_public_projection_without_password_hash() -> None:
    client = _client()
    response = client.post(
        "/api/auth/register",
        json={"email": "a@b.com", "password": "password123", "first_name": "A", "last_name": "B"},
    )
    assert response.status_code == 201
    body = response.json()
    assert "password" not in body
    assert "password_hash" not in body
    assert body["email"] == "a@b.com"


def test_register_duplicate_email_returns_api_error_envelope() -> None:
    client = _client()
    _register_and_login(client)
    response = client.post(
        "/api/auth/register",
        json={"email": "A@B.com", "password": "password456", "first_name": "C", "last_name": "D"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "EMAIL_ALREADY_REGISTERED"
    assert "request_id" in body


def test_login_wrong_password_returns_401() -> None:
    client = _client()
    _register_and_login(client)
    response = client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong"})
    assert response.status_code == 401


def test_login_sets_session_and_csrf_cookies_with_expected_flags() -> None:
    client = _client()
    _register_and_login(client)
    login_response = client.post("/api/auth/login", json={"email": "a@b.com", "password": "password123"})
    set_cookie_headers = login_response.headers.get_list("set-cookie")
    session_header = next(h for h in set_cookie_headers if h.startswith("m4t_session="))
    csrf_header = next(h for h in set_cookie_headers if h.startswith("m4t_csrf="))

    assert "HttpOnly" in session_header
    assert "SameSite=lax" in session_header
    assert "Path=/" in session_header
    # Secure varsayılan false (local http demo) — SESSION_COOKIE_SECURE=false iken flag yok.
    assert "Secure" not in session_header

    assert "HttpOnly" not in csrf_header  # frontend JS okuyabilmeli


def test_me_without_session_cookie_is_401() -> None:
    client = _client()
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_with_valid_session_cookie_returns_current_user() -> None:
    client = _client()
    _register_and_login(client)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "a@b.com"


def test_logout_without_csrf_header_is_rejected() -> None:
    client = _client()
    _register_and_login(client)
    response = client.post("/api/auth/logout")
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_TOKEN_INVALID"


def test_logout_with_wrong_csrf_header_is_rejected() -> None:
    client = _client()
    _register_and_login(client)
    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": "not-the-real-token"})
    assert response.status_code == 403


def test_logout_with_correct_csrf_revokes_session() -> None:
    client = _client()
    _register_and_login(client)
    csrf = client.cookies.get("m4t_csrf")

    logout_response = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logout_response.status_code == 204

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 401


def test_csrf_rejects_mismatched_origin_header() -> None:
    client = _client()
    _register_and_login(client)
    csrf = client.cookies.get("m4t_csrf")

    response = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf, "Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_ORIGIN_MISMATCH"


def test_csrf_accepts_matching_origin_header() -> None:
    client = _client()
    _register_and_login(client)
    csrf = client.cookies.get("m4t_csrf")

    response = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
    )
    assert response.status_code == 204


def test_sessions_revoke_invalidates_all_sessions_for_user() -> None:
    client = _client()
    _register_and_login(client)
    csrf = client.cookies.get("m4t_csrf")

    response = client.post("/api/auth/sessions/revoke", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert response.json()["revoked"] == 1

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 401


def test_legacy_capability_token_does_not_satisfy_authenticated_user() -> None:
    """Query token'ı session değildir — `require_authenticated_user` hâlâ 401 döner."""
    client = _client()
    response = client.get("/api/auth/me", params={"token": "some-legacy-capability-token"})
    assert response.status_code == 401


def test_dependency_overrides_still_stub_get_current_actor_for_auth_router() -> None:
    """Yusuf'un Plan 03B testlerinin dayandığı kalıp: `dependency_overrides`
    üzerinden stub actor, gerçek session cookie'si olmadan router'ları
    çalıştırabilmeli."""
    conn = connect()
    init_db(conn)
    real_user_id = None
    try:
        from backend.app.services import auth as auth_service

        real_user_id = auth_service.register_user(
            conn, email="stub-target@example.com", password="password123",
            first_name="Stub", last_name="Target",
        )
        conn.commit()
    finally:
        conn.close()

    app = build_app_with_routers(auth_router)

    def stub_actor() -> ActorContext:
        return ActorContext(actor_type="user", user_id=real_user_id, auth_method="session")

    app.dependency_overrides[get_current_actor] = stub_actor
    try:
        client = TestClient(app)
        # Gerçek session cookie'si YOK — yalnızca override etkili.
        response = client.get("/api/auth/me")
        assert response.status_code == 200
        assert response.json()["email"] == "stub-target@example.com"
    finally:
        app.dependency_overrides.clear()
