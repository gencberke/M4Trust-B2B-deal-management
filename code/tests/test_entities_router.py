"""`routers/entities.py` — isolated FastAPI app üzerinden HTTP-seviyesi testler."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.db import connect, init_db
from backend.app.routers.auth import router as auth_router
from backend.app.routers.entities import router as entities_router
from tests._identity_support import build_app_with_routers, identity_keys  # noqa: F401


def _client() -> TestClient:
    conn = connect()
    init_db(conn)
    conn.close()
    app = build_app_with_routers(auth_router, entities_router)
    return TestClient(app)


def _register_and_login(client: TestClient, *, email: str) -> None:
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "first_name": "A", "last_name": "B"},
    )
    assert r.status_code == 201
    r = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200


def _csrf_headers(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies.get("m4t_csrf")}


_ENTITY_PAYLOAD = {
    "entity_type": "company",
    "legal_name": "ABC Sanayi A.Ş.",
    "tax_identifier_type": "vkn",
    "tax_identifier": "1234567890",
    "tax_office": "Kadıköy",
}


def test_create_entity_makes_creator_owner(identity_keys) -> None:
    client = _client()
    _register_and_login(client, email="owner@example.com")

    response = client.post("/api/entities", json=_ENTITY_PAYLOAD, headers=_csrf_headers(client))

    assert response.status_code == 201
    body = response.json()
    assert body["my_role"] == "owner"
    assert body["legal_name"] == "ABC Sanayi A.Ş."
    assert body["tax_identifier_last4"] == "7890"


def test_entity_projection_never_leaks_ciphertext_or_hmac(identity_keys) -> None:
    client = _client()
    _register_and_login(client, email="owner2@example.com")
    response = client.post("/api/entities", json=_ENTITY_PAYLOAD, headers=_csrf_headers(client))
    body = response.json()

    assert "tax_identifier_ciphertext" not in body
    assert "tax_identifier_lookup_hmac" not in body
    assert "tax_identifier" not in body
    assert "1234567890" not in str(body)


def test_create_entity_requires_csrf(identity_keys) -> None:
    client = _client()
    _register_and_login(client, email="nocsrf@example.com")
    response = client.post("/api/entities", json=_ENTITY_PAYLOAD)
    assert response.status_code == 403


def test_list_entities_returns_only_own_entities(identity_keys) -> None:
    client = _client()
    _register_and_login(client, email="alice@example.com")
    client.post("/api/entities", json=_ENTITY_PAYLOAD, headers=_csrf_headers(client))

    other_payload = dict(_ENTITY_PAYLOAD, legal_name="XYZ Ltd.", tax_identifier="9876543210")
    _register_and_login(client, email="bob@example.com")
    client.post("/api/entities", json=other_payload, headers=_csrf_headers(client))

    response = client.get("/api/entities")
    names = {row["legal_name"] for row in response.json()}
    assert names == {"XYZ Ltd."}


def test_get_entity_by_unrelated_user_is_404(identity_keys) -> None:
    client = _client()
    _register_and_login(client, email="owner3@example.com")
    created = client.post("/api/entities", json=_ENTITY_PAYLOAD, headers=_csrf_headers(client)).json()

    _register_and_login(client, email="outsider@example.com")
    response = client.get(f"/api/entities/{created['id']}")
    assert response.status_code == 404


def test_patch_entity_by_owner_succeeds(identity_keys) -> None:
    client = _client()
    _register_and_login(client, email="owner4@example.com")
    created = client.post("/api/entities", json=_ENTITY_PAYLOAD, headers=_csrf_headers(client)).json()

    response = client.patch(
        f"/api/entities/{created['id']}",
        json={"legal_name": "ABC Yeni Unvan A.Ş."},
        headers=_csrf_headers(client),
    )
    assert response.status_code == 200
    assert response.json()["legal_name"] == "ABC Yeni Unvan A.Ş."


def test_patch_entity_by_member_role_is_forbidden(identity_keys) -> None:
    client = _client()
    _register_and_login(client, email="owner5@example.com")
    created = client.post("/api/entities", json=_ENTITY_PAYLOAD, headers=_csrf_headers(client)).json()

    _register_and_login(client, email="member5@example.com")
    member_me = client.get("/api/auth/me").json()

    conn = connect()
    conn.execute(
        "INSERT INTO memberships (id, user_id, legal_entity_id, role, status, created_at) "
        "VALUES ('mship-member5', ?, ?, 'member', 'active', 't')",
        (member_me["id"], created["id"]),
    )
    conn.commit()
    conn.close()

    response = client.patch(
        f"/api/entities/{created['id']}",
        json={"legal_name": "Should Not Work"},
        headers=_csrf_headers(client),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "ENTITY_ROLE_FORBIDDEN"


def test_member_role_can_still_read_entity(identity_keys) -> None:
    client = _client()
    _register_and_login(client, email="owner6@example.com")
    created = client.post("/api/entities", json=_ENTITY_PAYLOAD, headers=_csrf_headers(client)).json()

    _register_and_login(client, email="member6@example.com")
    member_me = client.get("/api/auth/me").json()

    conn = connect()
    conn.execute(
        "INSERT INTO memberships (id, user_id, legal_entity_id, role, status, created_at) "
        "VALUES ('mship-member6', ?, ?, 'member', 'active', 't')",
        (member_me["id"], created["id"]),
    )
    conn.commit()
    conn.close()

    response = client.get(f"/api/entities/{created['id']}")
    assert response.status_code == 200
    assert response.json()["my_role"] == "member"


def test_create_entity_rejects_wrong_length_tax_identifier(identity_keys) -> None:
    client = _client()
    _register_and_login(client, email="badtax@example.com")
    bad_payload = dict(_ENTITY_PAYLOAD, tax_identifier="123")
    response = client.post("/api/entities", json=bad_payload, headers=_csrf_headers(client))
    assert response.status_code == 422
