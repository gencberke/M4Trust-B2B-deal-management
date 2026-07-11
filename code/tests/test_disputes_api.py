"""Plan 05 / Faz 5B — `routers/disputes.py` izole app authorization testleri."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from backend.app.config import Settings
from backend.app.db import connect, get_db, init_db
from backend.app.middleware.request_id import RequestIDMiddleware
from backend.app.repositories import participants as participants_repo
from backend.app.services import participants as participants_service
from backend.app.services.access_control import ActorContext, get_current_actor
from backend.app.services import review as review_service

_disputes_migration = import_module("backend.app.db.migrations.014_disputes")
_evidence_migration = import_module("backend.app.db.migrations.013_evidence_records")

_TX_ID = "tx-5b-api"
_BUYER_ENTITY = "entity-buyer"
_SELLER_ENTITY = "entity-seller"


def _actor(user_id: str, entity_id: str, platform_role: str | None = None) -> ActorContext:
    return ActorContext(
        actor_type="user", user_id=user_id, acting_entity_id=entity_id, platform_role=platform_role,
        auth_method="session", request_id="req-5b-api",
    )


def _create_user(conn, user_id: str, email: str) -> None:
    conn.execute(
        "INSERT INTO users (id, email_normalized, password_hash, first_name, last_name, "
        "status, platform_role, created_at, updated_at) VALUES (?, ?, 'unused', 'T', 'U', "
        "'active', NULL, datetime('now'), datetime('now'))",
        (user_id, email),
    )


def _create_entity(conn, entity_id: str, created_by_user_id: str) -> None:
    conn.execute(
        "INSERT INTO legal_entities (id, entity_type, legal_name, tax_identifier_type, "
        "tax_identifier_ciphertext, tax_identifier_lookup_hmac, tax_identifier_last4, "
        "verification_status, created_by_user_id, created_at, updated_at) "
        "VALUES (?, 'company', ?, 'vkn', 'cipher', 'hmac', '1234', 'self_declared', ?, "
        "datetime('now'), datetime('now'))",
        (entity_id, f"Legal Entity {entity_id}", created_by_user_id),
    )


@pytest.fixture()
def conn(tmp_path: Path):
    connection = connect(Settings(db_path=tmp_path / "5b_api.db"))
    init_db(connection)
    _evidence_migration.apply(connection)
    _disputes_migration.apply(connection)

    for uid, email in (
        ("u-manager", "manager@example.com"),
        ("u-buyer-approver", "buyer-approver@example.com"),
        ("u-seller-approver", "seller-approver@example.com"),
        ("u-buyer-viewer", "buyer-viewer@example.com"),
        ("u-intruder", "intruder@example.com"),
    ):
        _create_user(connection, uid, email)
    _create_entity(connection, _BUYER_ENTITY, "u-manager")
    _create_entity(connection, _SELLER_ENTITY, "u-manager")

    connection.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES (?, 'awaiting_ratification', NULL, NULL, NULL, NULL, NULL, 'now', "
        "'account_v2', ?)",
        (_TX_ID, _BUYER_ENTITY),
    )

    manager_actor = _actor("u-manager", _BUYER_ENTITY)
    buyer_participant = participants_service.attach_creator(
        connection, _TX_ID, manager_actor, "buyer", _BUYER_ENTITY
    )
    participants_service.create_counterparty_placeholder(connection, _TX_ID, "seller", None)
    seller_row = participants_repo.get_participant(connection, _TX_ID, "seller")
    connection.execute(
        "UPDATE transaction_participants SET legal_entity_id = ? WHERE id = ?",
        (_SELLER_ENTITY, seller_row["id"]),
    )
    participants_repo.create_assignment(
        connection, transaction_id=_TX_ID, participant_id=buyer_participant.id,
        user_id="u-buyer-approver", legal_entity_id=_BUYER_ENTITY, role="approver",
    )
    participants_repo.create_assignment(
        connection, transaction_id=_TX_ID, participant_id=seller_row["id"],
        user_id="u-seller-approver", legal_entity_id=_SELLER_ENTITY, role="approver",
    )
    participants_repo.create_assignment(
        connection, transaction_id=_TX_ID, participant_id=buyer_participant.id,
        user_id="u-buyer-viewer", legal_entity_id=_BUYER_ENTITY, role="viewer",
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def _build_app(conn, actor: ActorContext | None) -> FastAPI:
    from backend.app.routers import disputes as disputes_router

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(disputes_router.router)

    def _get_db():
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()

    app.dependency_overrides[get_db] = _get_db
    if actor is not None:
        app.dependency_overrides[get_current_actor] = lambda: actor
    return app


def _post_open(conn, actor, milestone_id=None, reason_code="QUALITY_ISSUE"):
    app = _build_app(conn, actor)
    client = TestClient(app)
    return client.post(
        f"/api/transactions/{_TX_ID}/disputes",
        json={"milestone_id": milestone_id, "reason_code": reason_code, "description": "Ürün eksik geldi."},
    )


def test_buyer_approver_can_open_dispute(conn) -> None:
    response = _post_open(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "open"


def test_seller_approver_can_open_dispute(conn) -> None:
    response = _post_open(conn, _actor("u-seller-approver", _SELLER_ENTITY))
    assert response.status_code == 200, response.text


def test_manager_alone_cannot_open_dispute(conn) -> None:
    response = _post_open(conn, _actor("u-manager", _BUYER_ENTITY))
    assert response.status_code == 403
    assert response.json()["code"] == "DISPUTE_PARTICIPANT_APPROVER_REQUIRED"


def test_viewer_cannot_open_dispute(conn) -> None:
    response = _post_open(conn, _actor("u-buyer-viewer", _BUYER_ENTITY))
    assert response.status_code == 403


def test_unrelated_user_cannot_open_dispute(conn) -> None:
    response = _post_open(conn, _actor("u-intruder", _BUYER_ENTITY))
    assert response.status_code == 403


def test_anonymous_cannot_open_dispute(conn) -> None:
    response = _post_open(conn, ActorContext(actor_type="anonymous"))
    assert response.status_code == 401


def test_platform_reviewer_cannot_open_dispute_on_behalf_of_party(conn) -> None:
    response = _post_open(conn, _actor("u-reviewer-not-a-participant", _BUYER_ENTITY, platform_role="reviewer"))
    assert response.status_code == 403


def test_acting_entity_mismatch_is_rejected(conn) -> None:
    response = _post_open(conn, _actor("u-seller-approver", _BUYER_ENTITY))
    assert response.status_code == 403


def test_list_disputes_requires_transaction_access(conn) -> None:
    app = _build_app(conn, _actor("u-intruder", _BUYER_ENTITY))
    response = TestClient(app).get(f"/api/transactions/{_TX_ID}/disputes")
    assert response.status_code == 403


def test_list_disputes_visible_to_transaction_participant(conn) -> None:
    _post_open(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    app = _build_app(conn, _actor("u-buyer-viewer", _BUYER_ENTITY))
    response = TestClient(app).get(f"/api/transactions/{_TX_ID}/disputes")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_comment_action_by_approver_succeeds(conn) -> None:
    opened = _post_open(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    dispute_id = opened.json()["id"]
    app = _build_app(conn, _actor("u-seller-approver", _SELLER_ENTITY))
    response = TestClient(app).post(
        f"/api/disputes/{dispute_id}/actions", json={"action": "comment", "comment": "İnceleniyor."}
    )
    assert response.status_code == 200, response.text


def test_manager_cannot_comment_on_dispute(conn) -> None:
    opened = _post_open(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    dispute_id = opened.json()["id"]
    app = _build_app(conn, _actor("u-manager", _BUYER_ENTITY))
    response = TestClient(app).post(
        f"/api/disputes/{dispute_id}/actions", json={"action": "comment", "comment": "x"}
    )
    assert response.status_code == 403


def test_cancel_by_non_opener_is_rejected(conn) -> None:
    opened = _post_open(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    dispute_id = opened.json()["id"]
    app = _build_app(conn, _actor("u-seller-approver", _SELLER_ENTITY))
    response = TestClient(app).post(f"/api/disputes/{dispute_id}/actions", json={"action": "cancel"})
    assert response.status_code == 403
    assert response.json()["code"] == "DISPUTE_ACTION_FORBIDDEN"


def test_cancel_by_opener_succeeds(conn) -> None:
    opened = _post_open(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    dispute_id = opened.json()["id"]
    app = _build_app(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    response = TestClient(app).post(f"/api/disputes/{dispute_id}/actions", json={"action": "cancel"})
    assert response.status_code == 200, response.text
    assert response.json()["action"] == "cancel"


def test_sensitive_comment_is_rejected(conn) -> None:
    opened = _post_open(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    dispute_id = opened.json()["id"]
    app = _build_app(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    response = TestClient(app).post(
        f"/api/disputes/{dispute_id}/actions",
        json={"action": "comment", "comment": "iletişim: buyer@example.com"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "DISPUTE_CONTENT_REJECTED"


def test_escalate_dispute_requires_authorized_human_call(conn) -> None:
    """Review case var olsa bile, yalnız yetkili participant approver'ın açık
    `escalate_dispute` isteği dispute'u under_review'a taşır -- review case
    kendi başına dispute action üretmez (bu test bunun tersini de doğrular:
    manager review_case_id ile escalate DENEMESİ dahi yetkisizlik nedeniyle reddedilir)."""
    opened = _post_open(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    dispute_id = opened.json()["id"]
    case = review_service.open_case(
        conn, transaction_id=_TX_ID, phase="pre_ratification", source_type="system", source_id=None,
        reason_code="MANUAL_HOLD", title="t", description="d", severity="warning",
        actor_context=_actor("u-manager", _BUYER_ENTITY),
    )
    conn.commit()

    manager_app = _build_app(conn, _actor("u-manager", _BUYER_ENTITY))
    forbidden = TestClient(manager_app).post(
        f"/api/disputes/{dispute_id}/actions",
        json={"action": "escalate_dispute", "review_case_id": case.id},
    )
    assert forbidden.status_code == 403

    approver_app = _build_app(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    allowed = TestClient(approver_app).post(
        f"/api/disputes/{dispute_id}/actions",
        json={"action": "escalate_dispute", "review_case_id": case.id},
    )
    assert allowed.status_code == 200, allowed.text


# --- static checks -----------------------------------------------------------------


def test_router_has_no_manual_commit_call() -> None:
    module_path = (
        Path(__file__).resolve().parents[1] / "backend" / "app" / "routers" / "disputes.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in {"commit", "rollback"} and (
            isinstance(node.func.value, ast.Name) and node.func.value.id == "conn"
        ):
            pytest.fail(f"Beklenmeyen conn.{node.func.attr}() çağrısı router'da bulundu.")


def test_router_imports_no_payment_provider() -> None:
    module_path = (
        Path(__file__).resolve().parents[1] / "backend" / "app" / "routers" / "disputes.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    forbidden_prefixes = (
        "backend.app.services.payment_provider",
        "backend.app.services.payments.moka",
        "backend.app.services.payments.ports",
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in imported:
        assert not any(name == p or name.startswith(p + ".") for p in forbidden_prefixes), name
