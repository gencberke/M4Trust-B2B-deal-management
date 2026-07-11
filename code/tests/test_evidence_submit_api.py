"""Plan 05 / Faz 5A — `routers/evidence_submit.py` izole app authorization testleri."""

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
from backend.app.services.tracking_policy import create_draft_policy

_evidence_migration = import_module("backend.app.db.migrations.013_evidence_records")

_TX_ID = "tx-5a-api"
_BUYER_ENTITY = "entity-buyer"
_SELLER_ENTITY = "entity-seller"


def _actor(user_id: str, entity_id: str) -> ActorContext:
    return ActorContext(
        actor_type="user", user_id=user_id, acting_entity_id=entity_id,
        auth_method="session", request_id="req-5a-api",
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
    connection = connect(Settings(db_path=tmp_path / "5a_api.db"))
    init_db(connection)
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_records'"
    ).fetchone() is None:
        _evidence_migration.apply(connection)

    _create_user(connection, "u-manager", "manager@example.com")
    _create_user(connection, "u-seller-approver", "seller-approver@example.com")
    _create_user(connection, "u-buyer-approver", "buyer-approver@example.com")
    _create_user(connection, "u-intruder", "intruder@example.com")
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
        connection, transaction_id=_TX_ID, participant_id=seller_row["id"],
        user_id="u-seller-approver", legal_entity_id=_SELLER_ENTITY, role="approver",
    )
    participants_repo.create_assignment(
        connection, transaction_id=_TX_ID, participant_id=buyer_participant.id,
        user_id="u-buyer-approver", legal_entity_id=_BUYER_ENTITY, role="approver",
    )

    create_draft_policy(connection, _TX_ID)
    connection.execute(
        "UPDATE tracking_policies SET manager_physical_delivery_confirmed = 1, "
        "tracking_mode = 'document_and_video', status = 'locked', locked_at = 'now' "
        "WHERE transaction_id = ?",
        (_TX_ID,),
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def _build_app(conn, actor: ActorContext | None) -> FastAPI:
    from backend.app.routers import evidence_submit

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(evidence_submit.router)

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


def _post_e_irsaliye(conn, actor, external_reference="ext-1", delivered_quantity=10.0):
    app = _build_app(conn, actor)
    client = TestClient(app)
    return client.post(
        f"/api/transactions/{_TX_ID}/evidence/e-irsaliye",
        json={"external_reference": external_reference, "delivered_quantity": delivered_quantity},
    )


def test_anonymous_evidence_submission_is_rejected(conn) -> None:
    response = _post_e_irsaliye(conn, ActorContext(actor_type="anonymous"))
    assert response.status_code == 401


def test_unrelated_user_is_rejected(conn) -> None:
    response = _post_e_irsaliye(conn, _actor("u-intruder", _BUYER_ENTITY))
    assert response.status_code == 403
    assert response.json()["code"] == "EVIDENCE_SUBMITTER_FORBIDDEN"


def test_buyer_approver_is_rejected(conn) -> None:
    response = _post_e_irsaliye(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    assert response.status_code == 403
    assert response.json()["code"] == "EVIDENCE_SUBMITTER_FORBIDDEN"


def test_seller_assignment_is_accepted(conn) -> None:
    response = _post_e_irsaliye(conn, _actor("u-seller-approver", _SELLER_ENTITY))
    assert response.status_code == 200, response.text
    assert response.json()["verification_status"] == "verified"


def test_manager_is_accepted(conn) -> None:
    response = _post_e_irsaliye(conn, _actor("u-manager", _BUYER_ENTITY))
    assert response.status_code == 200, response.text


def test_acting_entity_mismatch_is_rejected(conn) -> None:
    # u-seller-approver gerçek assignment'ı entity-seller'a bağlı; buyer entity ile gelirse reddedilir.
    response = _post_e_irsaliye(conn, _actor("u-seller-approver", _BUYER_ENTITY))
    assert response.status_code == 403
    assert response.json()["code"] == "EVIDENCE_SUBMITTER_FORBIDDEN"


def test_duplicate_external_reference_conflict_returns_409(conn) -> None:
    actor = _actor("u-manager", _BUYER_ENTITY)
    first = _post_e_irsaliye(conn, actor, external_reference="ext-dup", delivered_quantity=10.0)
    assert first.status_code == 200
    second = _post_e_irsaliye(conn, actor, external_reference="ext-dup", delivered_quantity=99.0)
    assert second.status_code == 409
    assert second.json()["code"] == "EVIDENCE_IDEMPOTENCY_CONFLICT"


def test_video_evidence_upload_happy_path(conn) -> None:
    app = _build_app(conn, _actor("u-manager", _BUYER_ENTITY))
    client = TestClient(app)
    response = client.post(
        f"/api/transactions/{_TX_ID}/evidence/video",
        files={"file": ("delivery.mp4", b"fake-bytes", "video/mp4")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["storage_ref"] is not None
    assert len(body["file_sha256"]) == 64
    assert body["verification_status"] in {"verified", "review_required"}


# --- static checks -----------------------------------------------------------------


def test_router_has_no_manual_commit_call() -> None:
    """Statik AST kontrolü -- docstring'lerdeki `conn.commit()` sözcük geçişini
    değil, gerçek fonksiyon çağrısı düğümlerini arar (transaction ownership
    tamamen `get_db` dependency'sinde kalmalı)."""
    module_path = (
        Path(__file__).resolve().parents[1] / "backend" / "app" / "routers" / "evidence_submit.py"
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
        Path(__file__).resolve().parents[1] / "backend" / "app" / "routers" / "evidence_submit.py"
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
