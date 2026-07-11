"""Plan 04 / Wave B / Faz 4F-1 rule revision/revalidation API testleri."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from backend.app.config import Settings
from backend.app.db import connect, get_db, init_db
from backend.app.middleware.request_id import RequestIDMiddleware
from backend.app.repositories import participants as participants_repo
from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.schemas.payments import FundingScheduleSpec
from backend.app.services import ratification_package as package_service
from backend.app.services import participants as participants_service
from backend.app.services.access_control import ActorContext, get_current_actor
from backend.app.services.auth import create_session
from backend.app.services.payments.domain import MOKA_STANDARD_PROFILE
from backend.app.services import rule_versions
from backend.app.services.rule_versions import create_initial_from_extraction, validate_version
from backend.app.services.tracking_policy import create_draft_policy

_PAYLOAD = {
    "contract_id": "contract-4f",
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


def _actor(user_id: str = "u-owner", entity_id: str = "entity-owner") -> ActorContext:
    return ActorContext(
        actor_type="user",
        user_id=user_id,
        acting_entity_id=entity_id,
        auth_method="session",
        request_id="req-4f",
    )


def _make_db(tmp_path: Path):
    conn = connect(Settings(db_path=tmp_path / "4f.db"))
    init_db(conn)
    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES ('tx-4f', 'awaiting_approval', NULL, NULL, NULL, NULL, NULL, 'now', 'account_v2', ?)",
        ("entity-owner",),
    )
    participants_service.attach_creator(conn, "tx-4f", _actor(), "buyer", "entity-owner")
    conn.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) VALUES ('doc-4f', 'tx-4f', 1, "
        "'contract.md', 'tx-4f/doc-4f', 'doc-hash', 'active', 'now')"
    )
    conn.execute(
        "INSERT INTO extraction_runs (id, transaction_id, document_id, provider, model, "
        "prompt_version, schema_version, extraction_json, status, created_at) "
        "VALUES ('run-4f', 'tx-4f', 'doc-4f', 'fake', 'fake-v1', 'v1', 'v1', ?, 'ok', 'now')",
        (json.dumps(_PAYLOAD),),
    )
    version = create_initial_from_extraction(
        conn, transaction_id="tx-4f", extraction_run_id="run-4f", rules_payload=_PAYLOAD
    )
    validate_version(conn, version_id=version.id, confidence_threshold=0.7)
    conn.commit()
    return conn, version.id


def _app(conn, actor: ActorContext | None):
    from backend.app.routers import rule_sets

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(rule_sets.router)

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


def test_revision_is_immutable_parent_auto_validated_and_redacted(tmp_path: Path) -> None:
    conn, parent_id = _make_db(tmp_path)
    try:
        payload = deepcopy(_PAYLOAD)
        payload["contract_id"] = "contract-4f-revised"
        response = TestClient(_app(conn, _actor())).post(
            f"/api/transactions/tx-4f/rule-sets/{parent_id}/revisions", json=payload
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["version"] == 2
        assert body["status"] == "ratifiable"
        assert body["validator_status"] == "PASS"
        assert body["extraction"]["contract_id"] == "contract-4f-revised"
        assert "tax_id" not in json.dumps(body)
        assert "source_quote" not in json.dumps(body)

        parent = rule_sets_repo.get_by_id(conn, parent_id)
        assert parent["status"] == "superseded"
        assert parent["rules_json"] == rule_versions.canonical_rules_json(_PAYLOAD)
        event_types = {
            row["event_type"]
            for row in conn.execute("SELECT event_type FROM events WHERE transaction_id = 'tx-4f'")
        }
        assert {"rule_set_revised", "rules_validated"} <= event_types
        audit_row = conn.execute(
            "SELECT action, metadata_json FROM audit_events WHERE transaction_id = 'tx-4f' "
            "AND action = 'rule_set.revised'"
        ).fetchone()
        assert audit_row is not None
        assert "contract-4f-revised" not in audit_row["metadata_json"]
    finally:
        conn.close()


def test_needs_review_revision_opens_blocking_case_without_bypassing_old_case(tmp_path: Path) -> None:
    conn, parent_id = _make_db(tmp_path)
    try:
        from backend.app.services import review as review_service

        review_service.open_case(
            conn,
            transaction_id="tx-4f",
            phase="pre_ratification",
            source_type="system",
            source_id=None,
            reason_code="EXISTING_HOLD",
            title="hold",
            description="hold",
            severity="blocking",
            actor_context=_actor(),
        )
        payload = deepcopy(_PAYLOAD)
        payload["payment_rules"][0]["confidence"] = 0.1
        response = TestClient(_app(conn, _actor())).post(
            f"/api/transactions/tx-4f/rule-sets/{parent_id}/revisions", json=payload
        )

        assert response.status_code == 200, response.text
        assert response.json()["validator_status"] == "NEEDS_REVIEW"
        cases = conn.execute(
            "SELECT source_type, reason_code, severity, status FROM review_cases "
            "WHERE transaction_id = 'tx-4f' ORDER BY created_at"
        ).fetchall()
        assert [(row["reason_code"], row["severity"], row["status"]) for row in cases] == [
            ("EXISTING_HOLD", "blocking", "open"),
            ("VALIDATOR_NEEDS_REVIEW", "blocking", "open"),
        ]
    finally:
        conn.close()


def test_validate_endpoint_and_revision_supersede_current_package(tmp_path: Path) -> None:
    conn, parent_id = _make_db(tmp_path)
    try:
        create_draft_policy(conn, "tx-4f")
        conn.execute(
            "UPDATE tracking_policies SET manager_physical_delivery_confirmed = 1, "
            "tracking_mode = 'off', status = 'locked', locked_at = 'now' "
            "WHERE transaction_id = 'tx-4f'"
        )
        participants_service.create_counterparty_placeholder(conn, "tx-4f", "seller", None)
        participants = {
            row["role"]: row
            for row in participants_repo.list_participants(conn, "tx-4f")
        }
        for role, entity_id, snapshot in (
            ("buyer", "entity-owner", {"name": "Buyer A.Ş.", "tax_id": "1234567890"}),
            ("seller", "entity-seller", {"name": "Seller Ltd.", "tax_id": "9876543210"}),
        ):
            conn.execute(
                "UPDATE transaction_participants SET legal_entity_id = ?, status = 'confirmed', "
                "confirmed_snapshot_json = ?, confirmed_at = 'now', updated_at = 'now' WHERE id = ?",
                (entity_id, json.dumps(snapshot), participants[role]["id"]),
            )
        conn.execute("UPDATE transactions SET state = 'awaiting_ratification' WHERE id = 'tx-4f'")
        package = package_service.build_current_package(
            conn,
            transaction_id="tx-4f",
            funding_schedule_spec=FundingScheduleSpec(),
            capabilities=MOKA_STANDARD_PROFILE,
            actor_context=_actor(),
        )
        package = package_service.open_package(
            conn, package_id=package.id, actor_context=_actor()
        )
        conn.commit()

        payload = deepcopy(_PAYLOAD)
        payload["contract_id"] = "package-revision"
        response = TestClient(_app(conn, _actor())).post(
            f"/api/transactions/tx-4f/rule-sets/{parent_id}/revisions", json=payload
        )
        assert response.status_code == 200, response.text
        new_rule_id = response.json()["id"]
        old_package = conn.execute(
            "SELECT status FROM ratification_packages WHERE id = ?", (package.id,)
        ).fetchone()
        new_package = conn.execute(
            "SELECT status, rule_set_version_id FROM ratification_packages "
            "WHERE transaction_id = 'tx-4f' ORDER BY version DESC LIMIT 1"
        ).fetchone()
        assert old_package["status"] == "superseded"
        assert new_package["status"] == "draft"
        assert new_package["rule_set_version_id"] == new_rule_id

        validate_response = TestClient(_app(conn, _actor())).post(
            f"/api/transactions/tx-4f/rule-sets/{new_rule_id}/validate"
        )
        assert validate_response.status_code == 200, validate_response.text
        assert validate_response.json()["validator_status"] == "PASS"
    finally:
        conn.close()


def test_stale_parent_and_unauthorized_manager_are_rejected(tmp_path: Path) -> None:
    conn, parent_id = _make_db(tmp_path)
    try:
        first_payload = deepcopy(_PAYLOAD)
        first_payload["contract_id"] = "first"
        client = TestClient(_app(conn, _actor()))
        first = client.post(
            f"/api/transactions/tx-4f/rule-sets/{parent_id}/revisions", json=first_payload
        )
        assert first.status_code == 200

        stale = client.post(
            f"/api/transactions/tx-4f/rule-sets/{parent_id}/revisions", json=_PAYLOAD
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "STALE_RULE_SET_VERSION"

        participants_repo.create_assignment(
            conn,
            transaction_id="tx-4f",
            participant_id=None,
            user_id="u-other",
            legal_entity_id="entity-other",
            role="manager",
        )
        current_id = conn.execute(
            "SELECT id FROM rule_set_versions WHERE transaction_id = 'tx-4f' "
            "AND status != 'superseded'"
        ).fetchone()[0]
        forbidden = TestClient(_app(conn, _actor("u-other", "entity-other"))).post(
            f"/api/transactions/tx-4f/rule-sets/{current_id}/revisions", json=_PAYLOAD
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "RULE_REVISION_FORBIDDEN"
    finally:
        conn.close()


def test_legacy_and_post_funding_transactions_are_fail_closed(tmp_path: Path) -> None:
    conn, parent_id = _make_db(tmp_path)
    try:
        client = TestClient(_app(conn, _actor()))
        conn.execute("UPDATE transactions SET lifecycle_version = 'legacy_v1' WHERE id = 'tx-4f'")
        legacy = client.post(
            f"/api/transactions/tx-4f/rule-sets/{parent_id}/revisions", json=_PAYLOAD
        )
        assert legacy.status_code == 409
        assert legacy.json()["code"] == "LEGACY_RULE_REVISION_FORBIDDEN"

        conn.execute(
            "UPDATE transactions SET lifecycle_version = 'account_v2', state = 'funding_pending' "
            "WHERE id = 'tx-4f'"
        )
        post_funding = client.post(
            f"/api/transactions/tx-4f/rule-sets/{parent_id}/revisions", json=_PAYLOAD
        )
        assert post_funding.status_code == 409
        assert post_funding.json()["code"] == "RULE_REVISION_AFTER_RATIFICATION"
    finally:
        conn.close()


def test_revision_requires_csrf_for_real_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from reviews_fixtures import create_real_session, create_real_user

    conn, parent_id = _make_db(tmp_path)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "4f.db"))
    user_id = create_real_user(conn, email_normalized="owner@example.com", user_id="u-owner")
    session = create_real_session(conn, user_id=user_id)
    conn.commit()
    client = TestClient(_app(conn, None))
    client.cookies.set("m4t_session", session.raw_token)
    missing = client.post(
        f"/api/transactions/tx-4f/rule-sets/{parent_id}/revisions", json=_PAYLOAD
    )
    assert missing.status_code == 403
    assert missing.json()["code"] == "CSRF_TOKEN_INVALID"
    conn.close()


def test_main_wires_rule_sets_router() -> None:
    from backend.app.main import create_app

    paths = set(create_app().openapi()["paths"])
    assert "/api/transactions/{transaction_id}/rule-sets/{version_id}/revisions" in paths
    assert "/api/transactions/{transaction_id}/rule-sets/{version_id}/validate" in paths
