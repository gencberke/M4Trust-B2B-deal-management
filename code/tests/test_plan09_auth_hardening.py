"""Plan 09 auth abuse controls, reset and verification API tests."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from backend.app.db import connect, init_db
from backend.app.routers import auth as auth_router
from backend.app.services.notifications import FakeNotificationProvider
from tests._identity_support import build_app_with_routers


def _client(provider: FakeNotificationProvider | None = None) -> tuple[TestClient, FakeNotificationProvider]:
    conn = connect()
    init_db(conn)
    conn.close()
    app = build_app_with_routers(auth_router.router)
    provider = provider or FakeNotificationProvider()
    app.dependency_overrides[auth_router.get_auth_notification_provider] = lambda: provider
    return TestClient(app), provider


def _register(client: TestClient, email: str = "secure@example.com") -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "old-password-123",
            "first_name": "Secure",
            "last_name": "User",
        },
    )
    assert response.status_code == 201


def _token_from_link(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


def test_ip_email_login_window_returns_429_without_trusting_forwarded_header(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LOGIN_RATE_LIMIT_ATTEMPTS", "2")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "false")
    client, _ = _client()
    _register(client)
    headers = {"X-Forwarded-For": "203.0.113.10"}
    for _ in range(2):
        response = client.post(
            "/api/auth/login",
            json={"email": "secure@example.com", "password": "wrong"},
            headers=headers,
        )
        assert response.status_code == 401
    limited = client.post(
        "/api/auth/login",
        json={"email": "secure@example.com", "password": "wrong"},
        headers={"X-Forwarded-For": "198.51.100.99"},
    )
    assert limited.status_code == 429
    assert limited.json()["code"] == "AUTH_RATE_LIMITED"


def test_account_lockout_is_persistent_and_audited(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("ACCOUNT_LOCKOUT_THRESHOLD", "2")
    client, _ = _client()
    _register(client)
    for _ in range(2):
        assert client.post(
            "/api/auth/login",
            json={"email": "secure@example.com", "password": "wrong"},
        ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "secure@example.com", "password": "old-password-123"},
    ).status_code == 401

    conn = connect()
    try:
        user = conn.execute(
            "SELECT failed_login_count,locked_until FROM users WHERE email_normalized=?",
            ("secure@example.com",),
        ).fetchone()
        assert user["failed_login_count"] == 2 and user["locked_until"]
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='auth.account_locked'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_password_reset_is_hashed_single_use_and_revokes_sessions() -> None:
    client, provider = _client()
    _register(client)
    assert client.post(
        "/api/auth/login",
        json={"email": "secure@example.com", "password": "old-password-123"},
    ).status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    known = client.post(
        "/api/auth/password-reset/request", json={"email": "secure@example.com"}
    )
    unknown = client.post(
        "/api/auth/password-reset/request", json={"email": "unknown@example.com"}
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == {"accepted": True}
    token = _token_from_link(provider.delivery_links[-1])

    conn = connect()
    try:
        stored = conn.execute(
            "SELECT token_hash FROM auth_action_tokens WHERE purpose='password_reset'"
        ).fetchone()[0]
        assert stored != token and token not in stored
    finally:
        conn.close()

    confirmed = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "new_password": "new-password-456"},
    )
    assert confirmed.status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "new_password": "another-password"},
    ).status_code == 400
    assert client.post(
        "/api/auth/login",
        json={"email": "secure@example.com", "password": "new-password-456"},
    ).status_code == 200


def test_email_verification_token_replay_and_enforcement(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "true")
    client, provider = _client()
    _register(client)
    verification_token = _token_from_link(provider.delivery_links[-1])
    blocked = client.post(
        "/api/auth/login",
        json={"email": "secure@example.com", "password": "old-password-123"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "EMAIL_VERIFICATION_REQUIRED"

    assert client.post(
        "/api/auth/email-verification/confirm", json={"token": verification_token}
    ).status_code == 200
    assert client.post(
        "/api/auth/email-verification/confirm", json={"token": verification_token}
    ).status_code == 400
    assert client.post(
        "/api/auth/login",
        json={"email": "secure@example.com", "password": "old-password-123"},
    ).status_code == 200
    assert client.get("/api/auth/me").json()["email_verified_at"] is not None
