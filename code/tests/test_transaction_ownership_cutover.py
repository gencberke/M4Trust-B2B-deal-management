"""Plan 03 / Faz 3C — transaction ownership cutover testleri.

Migration `007`, dual-mode `POST /api/transactions` (legacy_v1 ∥ account_v2),
list/detail scoping ve `canonical_state` projeksiyonu. Mevcut legacy senaryo
regresyonu (`test_api_flow.py` vb.) ayrı dosyalarda zaten kapsanır — burada
yalnız YENİ davranış test edilir.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.db import connect, init_db
from backend.app.routers.auth import router as auth_router
from backend.app.routers.entities import router as entities_router
from backend.app.routers.invitations import router as invitations_router
from backend.app.routers.participants import router as participants_router
from backend.app.routers.transactions import router as transactions_router
from tests._identity_support import build_app_with_routers, identity_keys  # noqa: F401

_SAMPLE_MARKDOWN = (
    "# Örnek Sözleşme\n\n"
    "Alıcı ile Satıcı arasında endüstriyel pompa alım satımı sözleşmesidir.\n"
    "Tarafların onayıyla ödeme yapılır.\n"
)

_ENTITY_PAYLOAD = {
    "entity_type": "company",
    "legal_name": "ABC Sanayi A.Ş.",
    "tax_identifier_type": "vkn",
    "tax_identifier": "1234567890",
}


def _full_app() -> TestClient:
    conn = connect()
    init_db(conn)
    conn.close()
    app = build_app_with_routers(
        auth_router, entities_router, transactions_router, participants_router, invitations_router
    )
    return TestClient(app)


def _register_login(client: TestClient, email: str) -> None:
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "first_name": "A", "last_name": "B"},
    )
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies.get("m4t_csrf")}


def _create_entity(client: TestClient, legal_name: str = "ABC Sanayi A.Ş.") -> str:
    payload = dict(_ENTITY_PAYLOAD, legal_name=legal_name)
    r = client.post("/api/entities", json=payload, headers=_csrf(client))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload_account_mode(
    client: TestClient,
    *,
    acting_entity_id: str,
    own_role: str = "buyer",
    counterparty_email: str | None = None,
) -> dict:
    data = {"acting_entity_id": acting_entity_id, "own_role": own_role}
    if counterparty_email is not None:
        data["counterparty_email"] = counterparty_email
    response = client.post(
        "/api/transactions",
        data=data,
        files={"file": ("sozlesme.md", io.BytesIO(_SAMPLE_MARKDOWN.encode()), "text/markdown")},
    )
    return response


# --- migration ---------------------------------------------------------------


def test_migration_007_adds_lifecycle_columns_with_legacy_backfill(tmp_path: Path) -> None:
    from backend.app.config import Settings

    conn = connect(Settings(db_path=tmp_path / "m.db"))
    init_db(conn)
    conn.execute(
        "INSERT INTO transactions (id, state, created_at) VALUES ('t1', 'uploaded', 'x')"
    )
    conn.commit()
    row = conn.execute(
        "SELECT lifecycle_version, created_by_user_id, owner_entity_id, content_sha256 "
        "FROM transactions WHERE id='t1'"
    ).fetchone()
    assert row["lifecycle_version"] == "legacy_v1"
    assert row["created_by_user_id"] is None
    assert row["owner_entity_id"] is None
    assert row["content_sha256"] is None
    conn.close()


# --- account-mode create -------------------------------------------------------


def test_account_create_requires_authentication(identity_keys) -> None:
    client = _full_app()
    response = _upload_account_mode(client, acting_entity_id="nonexistent", own_role="buyer")
    assert response.status_code == 401


def test_account_create_requires_active_membership(identity_keys) -> None:
    client = _full_app()
    _register_login(client, "creator@example.com")
    other_entity_id = "not-my-entity"
    response = _upload_account_mode(client, acting_entity_id=other_entity_id, own_role="buyer")
    assert response.status_code == 403
    assert response.json()["code"] == "ACTING_ENTITY_NOT_AUTHORIZED"


def test_account_create_rejects_invalid_own_role(identity_keys) -> None:
    client = _full_app()
    _register_login(client, "creator2@example.com")
    entity_id = _create_entity(client)
    response = _upload_account_mode(client, acting_entity_id=entity_id, own_role="not-a-role")
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_OWN_ROLE"


def test_account_create_succeeds_sets_lifecycle_and_hash(identity_keys) -> None:
    client = _full_app()
    _register_login(client, "creator3@example.com")
    entity_id = _create_entity(client)
    response = _upload_account_mode(client, acting_entity_id=entity_id, own_role="buyer")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lifecycle_version"] == "account_v2"
    assert body["own_role"] == "buyer"
    assert body["acting_entity_id"] == entity_id
    assert "buyer_link" not in body  # capability token üretilmez

    detail = client.get(f"/api/transactions/{body['id']}").json()
    assert detail["lifecycle_version"] == "account_v2"
    assert detail["canonical_state"] is None  # account_v2 kendi state machine'ini kullanır


def test_account_create_attaches_creator_participant_and_manager_assignment(identity_keys) -> None:
    client = _full_app()
    _register_login(client, "creator4@example.com")
    entity_id = _create_entity(client)
    created = _upload_account_mode(client, acting_entity_id=entity_id, own_role="seller").json()

    participants = client.get(f"/api/transactions/{created['id']}/participants").json()
    roles = {p["role"] for p in participants}
    assert roles == {"buyer", "seller"}
    seller = next(p for p in participants if p["role"] == "seller")
    assert seller["status"] == "ready"
    buyer_placeholder = next(p for p in participants if p["role"] == "buyer")
    assert buyer_placeholder["status"] == "invited"


def test_account_create_with_counterparty_email_creates_invitation(identity_keys) -> None:
    client = _full_app()
    _register_login(client, "creator5@example.com")
    entity_id = _create_entity(client)
    created = _upload_account_mode(
        client, acting_entity_id=entity_id, own_role="buyer", counterparty_email="seller@example.com"
    ).json()

    assert created["invitation"] is not None
    assert created["invitation"]["participant_role"] == "seller"
    invite_link = created["invitation"]["invite_link"]
    token = invite_link.rsplit("/", 2)[1]

    preview = client.get(f"/api/invitations/{token}/preview")
    assert preview.status_code == 200


def test_account_create_without_email_has_no_invitation(identity_keys) -> None:
    client = _full_app()
    _register_login(client, "creator6@example.com")
    entity_id = _create_entity(client)
    created = _upload_account_mode(client, acting_entity_id=entity_id, own_role="buyer").json()
    assert created["invitation"] is None


# --- list/detail scoping -------------------------------------------------------


def test_list_transactions_scoped_to_assigned_user(identity_keys) -> None:
    client = _full_app()
    _register_login(client, "alice2@example.com")
    entity_a = _create_entity(client, "Alice A.Ş.")
    tx_a = _upload_account_mode(client, acting_entity_id=entity_a, own_role="buyer").json()

    _register_login(client, "bob2@example.com")
    entity_b = _create_entity(client, "Bob Ltd.")
    tx_b = _upload_account_mode(client, acting_entity_id=entity_b, own_role="buyer").json()

    # Bob artık son giriş yapan; yalnız kendi işlemini görmeli.
    listed_ids = {row["id"] for row in client.get("/api/transactions").json()}
    assert tx_b["id"] in listed_ids
    assert tx_a["id"] not in listed_ids


def test_account_detail_requires_auth_for_unrelated_anonymous_request(identity_keys) -> None:
    client = _full_app()
    _register_login(client, "owner-detail@example.com")
    entity_id = _create_entity(client)
    created = _upload_account_mode(client, acting_entity_id=entity_id, own_role="buyer").json()

    anon_client = _full_app()
    response = anon_client.get(f"/api/transactions/{created['id']}")
    assert response.status_code == 401


def test_account_detail_rejects_unrelated_authenticated_user(identity_keys) -> None:
    client = _full_app()
    _register_login(client, "owner-detail2@example.com")
    entity_id = _create_entity(client)
    created = _upload_account_mode(client, acting_entity_id=entity_id, own_role="buyer").json()

    outsider = _full_app()
    _register_login(outsider, "outsider@example.com")
    response = outsider.get(f"/api/transactions/{created['id']}")
    assert response.status_code == 403


def test_account_detail_accessible_to_assigned_creator(identity_keys) -> None:
    client = _full_app()
    _register_login(client, "owner-detail3@example.com")
    entity_id = _create_entity(client)
    created = _upload_account_mode(client, acting_entity_id=entity_id, own_role="buyer").json()

    response = client.get(f"/api/transactions/{created['id']}")
    assert response.status_code == 200


# --- end-to-end integration gate (program_haritasi §Wave 1 gate) --------------


def test_account_mode_end_to_end_onboarding_gate(identity_keys) -> None:
    """register creator -> entity -> authenticated upload -> creator participant
    -> invite counterparty -> counterparty register -> accept -> confirm profile."""
    client = _full_app()
    _register_login(client, "gate-creator@example.com")
    creator_entity = _create_entity(client, "Gate Alıcı A.Ş.")

    created = _upload_account_mode(
        client,
        acting_entity_id=creator_entity,
        own_role="buyer",
        counterparty_email="gate-counterparty@example.com",
    ).json()
    transaction_id = created["id"]
    invite_link = created["invitation"]["invite_link"]
    invite_token = invite_link.rsplit("/", 2)[1]

    # Pipeline (BackgroundTasks) TestClient içinde senkron yürür — PASS bekleniyor.
    detail = client.get(f"/api/transactions/{transaction_id}").json()
    assert detail["state"] == "awaiting_approval"

    counterparty = _full_app()
    _register_login(counterparty, "gate-counterparty@example.com")
    counterparty_entity = _create_entity(counterparty, "Gate Satıcı Ltd.")

    accept = counterparty.post(
        f"/api/invitations/{invite_token}/accept", json={"legal_entity_id": counterparty_entity}
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["role"] == "seller"

    profile = counterparty.put(
        f"/api/transactions/{transaction_id}/participants/me/profile",
        json={"snapshot": {"name": "Gate Satıcı Ltd.", "contact_email": "gate-counterparty@example.com"}},
    )
    assert profile.status_code == 200, profile.text

    confirm = counterparty.post(f"/api/transactions/{transaction_id}/participants/me/confirm")
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "confirmed"

    participants = client.get(f"/api/transactions/{transaction_id}/participants").json()
    seller = next(p for p in participants if p["role"] == "seller")
    assert seller["confirmed"] is True


# --- canonical_state (legacy_v1) — v2 §2.8 projeksiyonu doğru sinyalle besleniyor mu ----


def _upload_legacy(client: TestClient, tmp_path: Path) -> dict:
    md_path = tmp_path / "sozlesme.md"
    md_path.write_text(_SAMPLE_MARKDOWN, encoding="utf-8")
    with md_path.open("rb") as fh:
        response = client.post(
            "/api/transactions", files={"file": ("sozlesme.md", fh, "text/markdown")}
        )
    assert response.status_code == 200, response.text
    return response.json()


def _extract_token(link: str) -> str:
    return link.split("token=", 1)[1]


def test_canonical_state_preparation_before_lock_then_ready_for_ratification_after(
    client: TestClient, tmp_path: Path
) -> None:
    created = _upload_legacy(client, tmp_path)
    tx_id = created["id"]
    manager_token = _extract_token(created["manager_link"])

    detail = client.get(f"/api/transactions/{tx_id}").json()
    assert detail["lifecycle_version"] == "legacy_v1"
    assert detail["canonical_state"] == "preparation"

    update = client.put(
        f"/api/transactions/{tx_id}/tracking-policy",
        json={"manager_token": manager_token, "physical_delivery_confirmed": True, "tracking_mode": "off"},
    )
    assert update.status_code == 200
    detail = client.get(f"/api/transactions/{tx_id}").json()
    assert detail["canonical_state"] == "preparation"  # henüz kilitli değil

    lock = client.post(
        f"/api/transactions/{tx_id}/tracking-policy/lock", json={"manager_token": manager_token}
    )
    assert lock.status_code == 200
    detail = client.get(f"/api/transactions/{tx_id}").json()
    assert detail["canonical_state"] == "ready_for_ratification"


def test_canonical_state_settled_after_full_capture(client: TestClient, tmp_path: Path) -> None:
    created = _upload_legacy(client, tmp_path)
    tx_id = created["id"]
    manager_token = _extract_token(created["manager_link"])
    client.put(
        f"/api/transactions/{tx_id}/tracking-policy",
        json={"manager_token": manager_token, "physical_delivery_confirmed": True, "tracking_mode": "off"},
    )
    client.post(f"/api/transactions/{tx_id}/tracking-policy/lock", json={"manager_token": manager_token})

    buyer_token = _extract_token(created["buyer_link"])
    seller_token = _extract_token(created["seller_link"])
    client.post(f"/api/transactions/{tx_id}/approvals", json={"token": buyer_token})
    client.post(f"/api/transactions/{tx_id}/approvals", json={"token": seller_token})

    detail = client.get(f"/api/transactions/{tx_id}").json()
    assert detail["state"] == "decided"
    assert detail["canonical_state"] == "settled"


# --- LEGACY_CAPABILITY_ACCESS_ENABLED (Wave 3 hazırlığı, varsayılan true) -----


def test_legacy_capability_access_flag_defaults_enabled(
    client: TestClient, tmp_path: Path
) -> None:
    created = _upload_legacy(client, tmp_path)
    buyer_token = _extract_token(created["buyer_link"])
    response = client.get(
        f"/api/transactions/{created['id']}/party-view", params={"token": buyer_token}
    )
    assert response.status_code == 200


def test_legacy_capability_access_flag_disabled_rejects_party_view(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _upload_legacy(client, tmp_path)
    buyer_token = _extract_token(created["buyer_link"])

    monkeypatch.setenv("LEGACY_CAPABILITY_ACCESS_ENABLED", "false")
    response = client.get(
        f"/api/transactions/{created['id']}/party-view", params={"token": buyer_token}
    )
    assert response.status_code == 403


def test_legacy_capability_access_flag_disabled_rejects_delivery_evidence(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _upload_legacy(client, tmp_path)
    manager_token = _extract_token(created["manager_link"])
    client.put(
        f"/api/transactions/{created['id']}/tracking-policy",
        json={
            "manager_token": manager_token,
            "physical_delivery_confirmed": True,
            "tracking_mode": "document_only",
        },
    )
    client.post(
        f"/api/transactions/{created['id']}/tracking-policy/lock",
        json={"manager_token": manager_token},
    )
    seller_token = _extract_token(created["seller_link"])

    monkeypatch.setenv("LEGACY_CAPABILITY_ACCESS_ENABLED", "false")
    response = client.post(
        f"/api/transactions/{created['id']}/events/e-irsaliye",
        params={"token": seller_token},
        json={"delivered_quantity": 10},
    )
    assert response.status_code == 403
