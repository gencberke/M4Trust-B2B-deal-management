"""Plan 04 / Wave B / Faz 4E — `services/ratifications.py` + `routers/ratifications.py`
+ `routers/approvals.py` account cutover testleri.

Kritik kapsam: ratification mekaniği (idempotency, yetkilendirme, çift
ratification -> funding_pending, blocking review, provider çağrısı yok) ve
legacy/account approval ayrımı. CSRF/Origin/IDOR router seviyesinde, geri
kalan business-logic testleri servis seviyesinde (hızlı, izole app olmadan).
"""

from __future__ import annotations

import ast
import json
from importlib import import_module
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from backend.app.config import Settings
from backend.app.db import connect, get_db, init_db
from backend.app.repositories import packages as packages_repo
from backend.app.repositories import participants as participants_repo
from backend.app.schemas.payments import FundingScheduleSpec
from backend.app.services import participants as participants_service
from backend.app.services import ratification_package as package_service
from backend.app.services import ratifications as ratifications_service
from backend.app.services.access_control import ActorContext, get_current_actor
from backend.app.services.payments.domain import MOKA_STANDARD_PROFILE
from backend.app.services.payments.funding_coordinator import FundingCoordinatorError
from backend.app.services.tracking_policy import create_draft_policy


_PAYLOAD = {
    "contract_id": "contract-4e",
    "parties": {
        "buyer": {"name": "Buyer A.Ş.", "tax_id": "1234567890"},
        "seller": {"name": "Seller Ltd.", "tax_id": "9876543210"},
    },
    "commercial_terms": {
        "currency": "TRY",
        "total_amount": 100.0,
        "goods": [{"name": "Pompa", "quantity": 10.0, "unit": "adet"}],
        "delivery_deadline": "2026-09-01",
    },
    "payment_rules": [
        {
            "milestone": "Kabul",
            "trigger": "approval",
            "percentage": 100.0,
            "required_evidence": ["contract"],
            "source_quote": "Onay sonrası ödeme yapılır.",
            "confidence": 0.9,
        }
    ],
    "risk_flags": [],
    "needs_manual_review": False,
}


def _actor(user_id: str, entity_id: str) -> ActorContext:
    return ActorContext(
        actor_type="user",
        user_id=user_id,
        acting_entity_id=entity_id,
        auth_method="session",
        request_id="req-4e",
    )


def make_db(db_path=None):
    resolved = Path(db_path) if db_path is not None else Path(":memory:")
    conn = connect(Settings(db_path=resolved))
    init_db(conn)
    return conn


def _setup_open_package(conn, tx_id: str) -> str:
    """Buyer/seller confirmed + policy locked + rule PASS + package build+open. Package id döner."""
    from backend.app.services.rule_versions import create_initial_from_extraction, validate_version

    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES (?, 'awaiting_ratification', NULL, NULL, NULL, NULL, NULL, 'now', 'account_v2', ?)",
        (tx_id, "entity-buyer"),
    )
    create_draft_policy(conn, tx_id)
    conn.execute(
        "UPDATE tracking_policies SET manager_physical_delivery_confirmed = 1, "
        "tracking_mode = 'off', status = 'locked', locked_at = 'now' WHERE transaction_id = ?",
        (tx_id,),
    )

    participants_service.attach_creator(conn, tx_id, _actor("u-buyer", "entity-buyer"), "buyer", "entity-buyer")
    participants_service.create_counterparty_placeholder(conn, tx_id, "seller", None)
    rows = {
        row["role"]: row
        for row in conn.execute(
            "SELECT * FROM transaction_participants WHERE transaction_id = ?", (tx_id,)
        ).fetchall()
    }
    for role, entity_id, snapshot in (
        ("buyer", "entity-buyer", {"name": "Buyer A.Ş.", "tax_id": "1234567890"}),
        ("seller", "entity-seller", {"name": "Seller Ltd.", "tax_id": "9876543210"}),
    ):
        conn.execute(
            "UPDATE transaction_participants SET legal_entity_id = ?, status = 'confirmed', "
            "confirmed_snapshot_json = ?, confirmed_at = 'now', updated_at = 'now' WHERE id = ?",
            (entity_id, json.dumps(snapshot), rows[role]["id"]),
        )
    participants_repo.create_assignment(
        conn,
        transaction_id=tx_id,
        participant_id=rows["seller"]["id"],
        user_id="u-seller",
        legal_entity_id="entity-seller",
        role="manager",
    )

    document_id = f"doc-{tx_id}"
    run_id = f"run-{tx_id}"
    conn.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) VALUES (?, ?, 1, 'contract.md', "
        "?, 'document-hash', 'active', 'now')",
        (document_id, tx_id, f"{tx_id}/{document_id}"),
    )
    conn.execute(
        "INSERT INTO extraction_runs (id, transaction_id, document_id, provider, model, "
        "prompt_version, schema_version, extraction_json, status, created_at) "
        "VALUES (?, ?, ?, 'fake', 'fake-v1', 'v1', 'v1', ?, 'ok', 'now')",
        (run_id, tx_id, document_id, json.dumps(_PAYLOAD)),
    )
    version = create_initial_from_extraction(
        conn, transaction_id=tx_id, extraction_run_id=run_id, rules_payload=_PAYLOAD
    )
    validate_version(conn, version_id=version.id, confidence_threshold=0.7)

    package = package_service.build_current_package(
        conn,
        transaction_id=tx_id,
        funding_schedule_spec=FundingScheduleSpec(),
        capabilities=MOKA_STANDARD_PROFILE,
        actor_context=_actor("u-buyer", "entity-buyer"),
    )
    package = package_service.open_package(conn, package_id=package.id, actor_context=_actor("u-buyer", "entity-buyer"))
    conn.commit()
    return package.id


@pytest.fixture()
def ready(tmp_path):
    conn = make_db(tmp_path / "4e.db")
    tx_id = f"tx-{uuid4().hex[:8]}"
    package_id = _setup_open_package(conn, tx_id)
    try:
        yield conn, tx_id, package_id
    finally:
        conn.close()


# --- service-level: core ratification mechanics -------------------------------------


def test_first_ratification_does_not_complete_or_fund(ready) -> None:
    conn, tx_id, package_id = ready
    outcome = ratifications_service.create_ratification(
        conn, package_id=package_id, actor_context=_actor("u-buyer", "entity-buyer"), auth_method="session"
    )
    assert outcome.package_status.value == "open"
    assert outcome.funding_triggered is False


def test_second_ratification_completes_package_and_funds_once(ready) -> None:
    conn, tx_id, package_id = ready
    ratifications_service.create_ratification(
        conn, package_id=package_id, actor_context=_actor("u-buyer", "entity-buyer"), auth_method="session"
    )
    outcome = ratifications_service.create_ratification(
        conn, package_id=package_id, actor_context=_actor("u-seller", "entity-seller"), auth_method="session"
    )
    assert outcome.package_status.value == "complete"
    assert outcome.funding_triggered is True
    tx = conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    assert tx["state"] == "funding_pending"


def test_resubmit_same_participant_is_idempotent(ready) -> None:
    conn, tx_id, package_id = ready
    first = ratifications_service.create_ratification(
        conn, package_id=package_id, actor_context=_actor("u-buyer", "entity-buyer"), auth_method="session"
    )
    second = ratifications_service.create_ratification(
        conn, package_id=package_id, actor_context=_actor("u-buyer", "entity-buyer"), auth_method="session"
    )
    assert first.ratification.id == second.ratification.id


def test_actor_without_participant_is_rejected(ready) -> None:
    conn, tx_id, package_id = ready
    with pytest.raises(ratifications_service.RatificationAuthorizationError):
        ratifications_service.create_ratification(
            conn, package_id=package_id, actor_context=_actor("u-intruder", "entity-x"), auth_method="session"
        )


def test_same_user_cannot_ratify_both_sides(ready, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aynı user, önce buyer sonra (assignment değişikliğiyle) seller adına ratification denerse reddedilir."""
    conn, tx_id, package_id = ready
    ratifications_service.create_ratification(
        conn, package_id=package_id, actor_context=_actor("u-buyer", "entity-buyer"), auth_method="session"
    )
    seller_participant = conn.execute(
        "SELECT * FROM transaction_participants WHERE transaction_id=? AND role='seller'", (tx_id,)
    ).fetchone()
    seller_as_participant_obj = participants_service.list_participants(conn, tx_id)
    seller_obj = next(p for p in seller_as_participant_obj if p.role.value == "seller")
    assert seller_obj.id == seller_participant["id"]

    # u-buyer'ın (aynı kullanıcı) artık seller participant'ını temsil ettiğini simüle et.
    monkeypatch.setattr(
        ratifications_service.participants_service,
        "get_my_participant",
        lambda _conn, _tx, _uid: seller_obj,
    )
    with pytest.raises(ratifications_service.RatificationAuthorizationError):
        ratifications_service.create_ratification(
            conn, package_id=package_id, actor_context=_actor("u-buyer", "entity-seller"), auth_method="session"
        )


def test_superseded_package_cannot_be_ratified(ready) -> None:
    conn, tx_id, package_id = ready
    conn.execute("UPDATE ratification_packages SET status = 'superseded' WHERE id = ?", (package_id,))
    with pytest.raises(ratifications_service.RatificationConflictError) as exc:
        ratifications_service.create_ratification(
            conn, package_id=package_id, actor_context=_actor("u-buyer", "entity-buyer"), auth_method="session"
        )
    assert exc.value.reason_code == "PACKAGE_SUPERSEDED"


def test_cancelled_package_cannot_be_ratified(ready) -> None:
    conn, tx_id, package_id = ready
    conn.execute("UPDATE ratification_packages SET status = 'cancelled' WHERE id = ?", (package_id,))
    with pytest.raises(ratifications_service.RatificationConflictError) as exc:
        ratifications_service.create_ratification(
            conn, package_id=package_id, actor_context=_actor("u-buyer", "entity-buyer"), auth_method="session"
        )
    assert exc.value.reason_code == "PACKAGE_CANCELLED"


def test_blocking_review_prevents_funding_atomically(ready) -> None:
    conn, tx_id, package_id = ready
    from backend.app.services import review as review_service

    ratifications_service.create_ratification(
        conn, package_id=package_id, actor_context=_actor("u-buyer", "entity-buyer"), auth_method="session"
    )
    review_service.open_case(
        conn,
        transaction_id=tx_id,
        phase="pre_ratification",
        source_type="system",
        source_id=None,
        reason_code="MANUAL_HOLD",
        title="t",
        description="d",
        severity="blocking",
        actor_context=_actor("u-buyer", "entity-buyer"),
    )
    with pytest.raises(FundingCoordinatorError):
        ratifications_service.create_ratification(
            conn, package_id=package_id, actor_context=_actor("u-seller", "entity-seller"), auth_method="session"
        )
    conn.rollback()
    package = packages_repo.get_by_id(conn, package_id)
    assert package["status"] == "open"


def test_ratifications_module_imports_no_provider() -> None:
    for relative in ("services/ratifications.py", "routers/ratifications.py"):
        module_path = Path(__file__).resolve().parents[1] / "backend" / "app" / relative
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        forbidden_prefixes = (
            "backend.app.services.payment_provider",
            "backend.app.services.payments.moka",
            "backend.app.services.payments.ports",
            "httpx",
            "requests",
        )
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for name in imported:
            assert not any(name == p or name.startswith(p + ".") for p in forbidden_prefixes), name


# --- router: isolated app -------------------------------------------------------------


def _build_app(conn, actor_context=None) -> FastAPI:
    from backend.app.middleware.request_id import RequestIDMiddleware
    from backend.app.routers import ratifications as ratifications_router

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(ratifications_router.router)

    def _get_db():
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()

    app.dependency_overrides[get_db] = _get_db
    if actor_context is not None:
        app.dependency_overrides[get_current_actor] = lambda: actor_context
    return app


def test_build_open_endpoint_happy_path(tmp_path) -> None:
    conn = make_db(tmp_path / "router.db")
    tx_id = "tx-router-1"
    from backend.app.services.rule_versions import create_initial_from_extraction, validate_version

    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES (?, 'awaiting_ratification', NULL, NULL, NULL, NULL, NULL, 'now', 'account_v2', ?)",
        (tx_id, "entity-buyer"),
    )
    create_draft_policy(conn, tx_id)
    conn.execute(
        "UPDATE tracking_policies SET manager_physical_delivery_confirmed = 1, "
        "tracking_mode = 'off', status = 'locked', locked_at = 'now' WHERE transaction_id = ?",
        (tx_id,),
    )
    participants_service.attach_creator(conn, tx_id, _actor("u-buyer", "entity-buyer"), "buyer", "entity-buyer")
    participants_service.create_counterparty_placeholder(conn, tx_id, "seller", None)
    rows = {
        row["role"]: row
        for row in conn.execute(
            "SELECT * FROM transaction_participants WHERE transaction_id = ?", (tx_id,)
        ).fetchall()
    }
    for role, entity_id, snapshot in (
        ("buyer", "entity-buyer", {"name": "Buyer A.Ş.", "tax_id": "1234567890"}),
        ("seller", "entity-seller", {"name": "Seller Ltd.", "tax_id": "9876543210"}),
    ):
        conn.execute(
            "UPDATE transaction_participants SET legal_entity_id = ?, status = 'confirmed', "
            "confirmed_snapshot_json = ?, confirmed_at = 'now', updated_at = 'now' WHERE id = ?",
            (entity_id, json.dumps(snapshot), rows[role]["id"]),
        )
    document_id, run_id = "doc-router-1", "run-router-1"
    conn.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) VALUES (?, ?, 1, 'contract.md', "
        "'ref', 'document-hash', 'active', 'now')",
        (document_id, tx_id),
    )
    conn.execute(
        "INSERT INTO extraction_runs (id, transaction_id, document_id, provider, model, "
        "prompt_version, schema_version, extraction_json, status, created_at) "
        "VALUES (?, ?, ?, 'fake', 'fake-v1', 'v1', 'v1', ?, 'ok', 'now')",
        (run_id, tx_id, document_id, json.dumps(_PAYLOAD)),
    )
    version = create_initial_from_extraction(
        conn, transaction_id=tx_id, extraction_run_id=run_id, rules_payload=_PAYLOAD
    )
    validate_version(conn, version_id=version.id, confidence_threshold=0.7)
    conn.commit()

    app = _build_app(conn, actor_context=_actor("u-buyer", "entity-buyer"))
    client = TestClient(app)
    response = client.post(f"/api/transactions/{tx_id}/ratification-packages", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "open"
    assert "raw" not in json.dumps(body).lower()

    get_response = client.get(f"/api/transactions/{tx_id}/ratification-packages/current")
    assert get_response.status_code == 200
    assert get_response.json()["package_hash"] == body["package_hash"]
    conn.close()


def test_get_current_denies_unrelated_user_idor(ready) -> None:
    conn, tx_id, package_id = ready
    app = _build_app(conn, actor_context=_actor("u-intruder", "entity-x"))
    response = TestClient(app).get(f"/api/transactions/{tx_id}/ratification-packages/current")
    assert response.status_code == 403


def test_submit_ratification_requires_auth(ready) -> None:
    conn, tx_id, package_id = ready
    from backend.app.services.access_control import ActorContext as AC

    app = _build_app(conn, actor_context=AC(actor_type="anonymous"))
    response = TestClient(app).post(f"/api/ratification-packages/{package_id}/ratifications")
    assert response.status_code == 401


def test_submit_ratification_missing_csrf_rejected_with_real_session(tmp_path, monkeypatch) -> None:
    from reviews_fixtures import create_real_session, create_real_user

    db_path = tmp_path / "ratif_session.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    conn = make_db(str(db_path))
    tx_id = "tx-session-1"
    package_id = _setup_open_package(conn, tx_id)
    user_id = create_real_user(conn, email_normalized="buyer-session@example.com")
    conn.execute(
        "UPDATE transaction_assignments SET user_id = ? WHERE transaction_id = ? AND role = 'manager' "
        "AND legal_entity_id = 'entity-buyer'",
        (user_id, tx_id),
    )
    conn.commit()
    session = create_real_session(conn, user_id=user_id)
    conn.commit()

    app = _build_app(conn, actor_context=None)
    client = TestClient(app)
    client.cookies.set("m4t_session", session.raw_token)
    response = client.post(f"/api/ratification-packages/{package_id}/ratifications")
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_TOKEN_INVALID"
    conn.close()


def test_submit_ratification_correct_csrf_accepted(tmp_path, monkeypatch) -> None:
    from reviews_fixtures import create_real_session, create_real_user

    db_path = tmp_path / "ratif_session2.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    conn = make_db(str(db_path))
    tx_id = "tx-session-2"
    package_id = _setup_open_package(conn, tx_id)
    user_id = create_real_user(conn, email_normalized="buyer-session2@example.com")
    conn.execute(
        "UPDATE transaction_assignments SET user_id = ? WHERE transaction_id = ? AND role = 'manager' "
        "AND legal_entity_id = 'entity-buyer'",
        (user_id, tx_id),
    )
    conn.commit()
    session = create_real_session(conn, user_id=user_id)
    conn.commit()

    app = _build_app(conn, actor_context=None)
    client = TestClient(app)
    client.cookies.set("m4t_session", session.raw_token)
    response = client.post(
        f"/api/ratification-packages/{package_id}/ratifications",
        headers={"X-CSRF-Token": session.raw_csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["funding_triggered"] is False
    conn.close()


# --- approvals.py account cutover ------------------------------------------------------


def test_account_transaction_old_approval_endpoint_rejected(ready) -> None:
    conn, tx_id, package_id = ready
    from backend.app.routers import approvals as approvals_router

    app = FastAPI()
    app.include_router(approvals_router.router)

    def _get_db():
        try:
            yield conn
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    response = TestClient(app).post(f"/api/transactions/{tx_id}/approvals", json={"token": "whatever"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ACCOUNT_RATIFICATION_REQUIRED"
    conn.close()
