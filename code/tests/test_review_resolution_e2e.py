"""Plan 04 / Wave B / Faz 4F-2 — Berke'nin 4F-1'i (rule-revision-endpoints) ile gerçek E2E.

Rule revision → revalidate → resolve_continue → account transaction preparation'a
döner zincirini, `services/rule_versions.py` doğrudan çağırmak yerine gerçek
`routers/rule_sets.py` + `routers/reviews.py` uçları üzerinden HTTP ile doğrular
(program haritası 4F-2 kapanış talimatı: "Berke'nin 4F-1 PR'ı merge olduktan
sonra rebase et ve rule revision → revalidate → resolve_continue E2E testini
çalıştır").
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from backend.app.config import Settings
from backend.app.db import connect, get_db, init_db
from backend.app.middleware.request_id import RequestIDMiddleware
from backend.app.routers import reviews as reviews_router
from backend.app.routers import rule_sets as rule_sets_router
from backend.app.services import participants as participants_service
from backend.app.services.access_control import ActorContext, get_current_actor
from backend.app.services.rule_versions import create_initial_from_extraction, validate_version

_TX_ID = "tx-4f2-e2e"
_OWNER_ENTITY = "entity-owner"

# confidence 0.5 < default validator_confidence_threshold (0.7) -> NEEDS_REVIEW
_LOW_CONFIDENCE_PAYLOAD = {
    "contract_id": "contract-4f2-e2e",
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
            "confidence": 0.5,
        }
    ],
    "risk_flags": [],
    "needs_manual_review": False,
}

# Aynı payload, yalnız confidence yüksek -> revizyon sonrası PASS.
_FIXED_PAYLOAD = json.loads(json.dumps(_LOW_CONFIDENCE_PAYLOAD))
_FIXED_PAYLOAD["payment_rules"][0]["confidence"] = 0.95


def _owner_actor(user_id: str = "u-owner") -> ActorContext:
    """rule-sets uçları: yalnız creator-side manager (owner_entity_id eşleşmesi)."""
    return ActorContext(
        actor_type="user",
        user_id=user_id,
        acting_entity_id=_OWNER_ENTITY,
        auth_method="session",
        request_id="req-4f2-e2e",
    )


def _reviewer_actor(user_id: str = "u-reviewer") -> ActorContext:
    """reviews uçları: state-changing action'lar yalnız platform reviewer/admin."""
    return ActorContext(
        actor_type="user",
        user_id=user_id,
        platform_role="reviewer",
        auth_method="session",
        request_id="req-4f2-e2e-reviewer",
    )


def _make_db(tmp_path: Path):
    conn = connect(Settings(db_path=tmp_path / "4f2_e2e.db"))
    init_db(conn)
    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES (?, 'awaiting_review', NULL, NULL, NULL, NULL, NULL, 'now', 'account_v2', ?)",
        (_TX_ID, _OWNER_ENTITY),
    )
    participants_service.attach_creator(conn, _TX_ID, _owner_actor(), "buyer", _OWNER_ENTITY)
    conn.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) VALUES ('doc-4f2', ?, 1, "
        "'contract.md', ?, 'doc-hash', 'active', 'now')",
        (_TX_ID, f"{_TX_ID}/doc-4f2"),
    )
    conn.execute(
        "INSERT INTO extraction_runs (id, transaction_id, document_id, provider, model, "
        "prompt_version, schema_version, extraction_json, status, created_at) "
        "VALUES ('run-4f2', ?, 'doc-4f2', 'fake', 'fake-v1', 'v1', 'v1', ?, 'ok', 'now')",
        (_TX_ID, json.dumps(_LOW_CONFIDENCE_PAYLOAD)),
    )
    version = create_initial_from_extraction(
        conn, transaction_id=_TX_ID, extraction_run_id="run-4f2", rules_payload=_LOW_CONFIDENCE_PAYLOAD
    )
    # Gerçek pipeline davranışını taklit eder (transaction_pipeline.py):
    # NEEDS_REVIEW -> blocking pre_ratification case (validator kaynaklı).
    validated = validate_version(conn, version_id=version.id, confidence_threshold=0.7)
    assert validated.validator_status == "NEEDS_REVIEW"
    from backend.app.services import review as review_service

    case = review_service.open_validator_case(
        conn,
        transaction_id=_TX_ID,
        source_id=version.id,
        validator_status=validated.validator_status,
        finding_codes=["LOW_CONFIDENCE"],
        actor_context=_owner_actor(),
    )
    conn.commit()
    return conn, version.id, case.id


def _build_app(conn, actor: ActorContext) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(rule_sets_router.router)
    app.include_router(reviews_router.router)

    def _get_db():
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_actor] = lambda: actor
    return app


def test_rule_revision_revalidate_resolve_continue_returns_to_preparation(tmp_path) -> None:
    conn, old_version_id, case_id = _make_db(tmp_path)
    owner_client = TestClient(_build_app(conn, _owner_actor()))
    reviewer_client = TestClient(_build_app(conn, _reviewer_actor()))

    # 1) resolve_continue henüz mümkün değil -- revizyon yapılmadı.
    blocked = reviewer_client.post(f"/api/reviews/{case_id}/actions", json={"action": "resolve_continue"})
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "REVIEW_RESOLUTION_PRECONDITION_FAILED"

    # 2) Gerçek 4F-1 ucu: revizyon oluştur + otomatik revalidate (PASS). Yalnız
    # creator-side manager (owner_entity_id eşleşen actor) yapabilir.
    revision_response = owner_client.post(
        f"/api/transactions/{_TX_ID}/rule-sets/{old_version_id}/revisions",
        json=_FIXED_PAYLOAD,
    )
    assert revision_response.status_code == 200, revision_response.text
    revised = revision_response.json()
    assert revised["validator_status"] == "PASS"
    assert revised["status"] == "ratifiable"
    assert revised["id"] != old_version_id

    # 3) Eski version artık current değil -> resolve_continue şimdi izinli
    # (yalnız platform reviewer/admin yapabilir).
    resolved = reviewer_client.post(f"/api/reviews/{case_id}/actions", json={"action": "resolve_continue"})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["action"] == "resolve_continue"

    case_after = conn.execute(
        "SELECT status FROM review_cases WHERE id = ?", (case_id,)
    ).fetchone()
    assert case_after["status"] == "resolved"

    # 4) Son blocking pre_ratification case de temizlendiği için preparation'a döndü.
    tx_after = conn.execute("SELECT state FROM transactions WHERE id = ?", (_TX_ID,)).fetchone()
    assert tx_after["state"] == "preparation"

    # 5) Aynı case'e tekrar resolve_continue -- artık kapalı, closed hatası.
    replay = reviewer_client.post(f"/api/reviews/{case_id}/actions", json={"action": "resolve_continue"})
    assert replay.status_code == 409
    assert replay.json()["code"] == "REVIEW_CASE_CLOSED"


def test_revision_that_still_needs_review_keeps_case_unresolvable(tmp_path) -> None:
    """Revizyon PASS üretmezse (hâlâ NEEDS_REVIEW) eski case resolve edilemez."""
    conn, old_version_id, case_id = _make_db(tmp_path)
    owner_client = TestClient(_build_app(conn, _owner_actor()))
    reviewer_client = TestClient(_build_app(conn, _reviewer_actor()))

    still_low_confidence = json.loads(json.dumps(_LOW_CONFIDENCE_PAYLOAD))
    revision_response = owner_client.post(
        f"/api/transactions/{_TX_ID}/rule-sets/{old_version_id}/revisions",
        json=still_low_confidence,
    )
    assert revision_response.status_code == 200, revision_response.text
    assert revision_response.json()["validator_status"] == "NEEDS_REVIEW"

    resolve_attempt = reviewer_client.post(
        f"/api/reviews/{case_id}/actions", json={"action": "resolve_continue"}
    )
    assert resolve_attempt.status_code == 409
    assert resolve_attempt.json()["code"] == "REVIEW_RESOLUTION_PRECONDITION_FAILED"
