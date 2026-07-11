"""Plan 05 kapanış gate'i: evidence -> review/dispute guard -> release."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.repositories import participants as participants_repo
from backend.app.services import disputes as disputes_service
from backend.app.services import evidence_records as evidence_service
from backend.app.services import review as review_service
from backend.app.services import settlement
from backend.app.services.access_control import ActorContext
from reviews_fixtures import build_reviews_app, create_real_session, create_real_user
from test_ratifications import _setup_open_package, make_db


def test_main_wires_plan05_routers() -> None:
    paths = set(create_app().openapi()["paths"])
    assert "/api/transactions/{transaction_id}/evidence/e-irsaliye" in paths
    assert "/api/transactions/{transaction_id}/evidence/video" in paths
    assert "/api/transactions/{transaction_id}/disputes" in paths
    assert "/api/disputes/{dispute_id}/actions" in paths


def _actor(user_id: str, entity_id: str) -> ActorContext:
    return ActorContext(
        actor_type="user",
        user_id=user_id,
        acting_entity_id=entity_id,
        auth_method="session",
        request_id="req-plan05-close",
    )


def _create_entity(conn, entity_id: str, user_id: str) -> None:
    conn.execute(
        "INSERT INTO legal_entities (id, entity_type, legal_name, tax_identifier_type, "
        "tax_identifier_ciphertext, tax_identifier_lookup_hmac, tax_identifier_last4, "
        "verification_status, created_by_user_id, created_at, updated_at) "
        "VALUES (?, 'company', ?, 'vkn', 'cipher', 'hmac', '1234', 'self_declared', ?, "
        "'now', 'now')",
        (entity_id, entity_id, user_id),
    )


def _prepare_account_transaction(conn, transaction_id: str) -> None:
    buyer_user_id = create_real_user(
        conn, email_normalized="plan05-buyer@example.com", user_id="u-buyer"
    )
    seller_user_id = create_real_user(
        conn, email_normalized="plan05-seller@example.com", user_id="u-seller"
    )
    _create_entity(conn, "entity-buyer", buyer_user_id)
    _create_entity(conn, "entity-seller", seller_user_id)
    _setup_open_package(conn, transaction_id)

    # Plan 05 account fixture'i funding cutover'ından önce gerçek bir funded
    # transaction gibi davranır; 015-017 registry'ye alınmadığı için bu satır
    # bilinçli olarak fixture tarafından sağlanır.
    conn.execute(
        "UPDATE transactions SET state = 'active' WHERE id = ?", (transaction_id,)
    )
    conn.execute(
        "UPDATE tracking_policies SET manager_physical_delivery_confirmed = 1, "
        "tracking_mode = 'document_and_video', status = 'locked', locked_at = 'now' "
        "WHERE transaction_id = ?",
        (transaction_id,),
    )
    conn.executemany(
        "INSERT INTO approvals (transaction_id, party, created_at) VALUES (?, ?, 'now')",
        [(transaction_id, "buyer"), (transaction_id, "seller")],
    )
    conn.execute(
        "INSERT INTO mock_payments (transaction_id, other_trx_code, virtual_pos_order_id, "
        "status, amount, created_at) VALUES (?, ?, 'order-plan05', 'pool', 100.0, 'now')",
        (transaction_id, transaction_id),
    )
    conn.commit()


def _add_real_memberships_and_approvers(conn, transaction_id: str) -> None:
    participants = {
        row["role"]: row
        for row in conn.execute(
            "SELECT * FROM transaction_participants WHERE transaction_id = ?", (transaction_id,)
        ).fetchall()
    }
    for membership_id, user_id, entity_id in (
        ("membership-plan05-buyer", "u-buyer", "entity-buyer"),
        ("membership-plan05-seller", "u-seller", "entity-seller"),
    ):
        conn.execute(
            "INSERT INTO memberships (id, user_id, legal_entity_id, role, status, created_at) "
            "VALUES (?, ?, ?, 'member', 'active', 'now')",
            (membership_id, user_id, entity_id),
        )
    for user_id, entity_id, role in (
        ("u-buyer", "entity-buyer", "buyer"),
        ("u-seller", "entity-seller", "seller"),
    ):
        participants_repo.create_assignment(
            conn,
            transaction_id=transaction_id,
            participant_id=participants[role]["id"],
            user_id=user_id,
            legal_entity_id=entity_id,
            role="approver",
        )


def _session_headers(session, entity_id: str) -> dict[str, str]:
    return {
        "X-CSRF-Token": session.raw_csrf_token,
        "X-Acting-Entity-ID": entity_id,
    }


def test_video_anomaly_opens_review_and_dispute_blocks_release_until_resolved(
    tmp_path: Path,
) -> None:
    transaction_id = "tx-plan05-close"
    conn = make_db(tmp_path / "plan05-close.db")
    _prepare_account_transaction(conn, transaction_id)
    seller = _actor("u-seller", "entity-seller")

    evidence_service.submit_evidence(
        conn,
        transaction_id=transaction_id,
        milestone_id=None,
        evidence_type="e_irsaliye",
        source="external_api",
        actor_context=seller,
        payload={"delivered_quantity": 10},
        verification_status="verified",
        external_reference="irsaliye-plan05",
    )
    anomalous_video = evidence_service.submit_evidence(
        conn,
        transaction_id=transaction_id,
        milestone_id=None,
        evidence_type="video",
        source="analyzer",
        actor_context=seller,
        payload={
            "counts": {},
            "unit_count": 7,
            "damage_signals": [],
            "confidence": 0.95,
        },
        verification_status="verified",
        external_reference="video-anomaly-plan05",
        storage_ref="tx-plan05/video-anomaly",
        file_sha256="a" * 64,
        analyzer_provider="fake",
        analyzer_version="v1",
    )
    conn.commit()

    first = settlement.evaluate_settlement(
        conn, transaction_id, Settings(db_path=tmp_path / "plan05-close.db")
    )
    assert first is not None
    assert first["action"] == "hold"
    assert "REVIEW_BLOCKING_RELEASE" in {item["code"] for item in first["findings"]}
    assert conn.execute(
        "SELECT COUNT(*) FROM review_cases WHERE transaction_id = ? "
        "AND source_type = 'video' AND status = 'open'",
        (transaction_id,),
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT status FROM mock_payments WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()[0] == "pool"
    assert conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()[0] == "active"

    dispute = disputes_service.open_dispute(
        conn,
        transaction_id=transaction_id,
        milestone_id=None,
        reason_code="QUALITY_ISSUE",
        description="Teslimat manuel inceleme bekliyor.",
        actor_context=seller,
    )
    disputes_service.record_dispute_action(
        conn,
        dispute_id=dispute.id,
        actor_context=seller,
        action="attach_evidence",
        evidence_id=anomalous_video.id,
    )
    conn.commit()

    blocked = settlement.evaluate_settlement(
        conn, transaction_id, Settings(db_path=tmp_path / "plan05-close.db")
    )
    assert blocked is not None
    assert blocked["action"] == "hold"
    blocked_codes = {item["code"] for item in blocked["findings"]}
    assert {"REVIEW_BLOCKING_RELEASE", "DISPUTE_BLOCKING_RELEASE"} <= blocked_codes

    disputes_service.record_dispute_action(
        conn,
        dispute_id=dispute.id,
        actor_context=seller,
        action="resolve",
        payload={"resolution_code": "QUALITY_REVIEWED"},
    )
    case = next(
        case
        for case in review_service.list_cases(conn, transaction_id)
        if case.source_type.value == "video"
    )
    review_service.resolve_case(
        conn,
        case_id=case.id,
        actor_context=seller,
        resolution_code="VIDEO_REVIEWED",
    )
    evidence_service.submit_evidence(
        conn,
        transaction_id=transaction_id,
        milestone_id=None,
        evidence_type="video",
        source="analyzer",
        actor_context=seller,
        payload={
            "counts": {},
            "unit_count": 10,
            "damage_signals": [],
            "confidence": 0.95,
        },
        verification_status="verified",
        external_reference="video-aligned-plan05",
        storage_ref="tx-plan05/video-aligned",
        file_sha256="b" * 64,
        analyzer_provider="fake",
        analyzer_version="v1",
    )
    conn.commit()

    released = settlement.evaluate_settlement(
        conn, transaction_id, Settings(db_path=tmp_path / "plan05-close.db")
    )
    assert released is not None
    assert released["action"] == "capture"
    assert conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()[0] == "active"
    assert conn.execute(
        "SELECT status FROM mock_payments WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()[0] == "released"
    conn.close()


def test_review_escalate_dispute_opens_new_dispute(tmp_path: Path) -> None:
    transaction_id = "tx-plan05-escalation"
    conn = make_db(tmp_path / "plan05-escalation.db")
    _prepare_account_transaction(conn, transaction_id)
    seller = conn.execute(
        "SELECT id FROM transaction_participants WHERE transaction_id = ? AND role = 'seller'",
        (transaction_id,),
    ).fetchone()
    participants_repo.create_assignment(
        conn,
        transaction_id=transaction_id,
        participant_id=seller["id"],
        user_id="u-seller",
        legal_entity_id="entity-seller",
        role="approver",
    )
    conn.commit()
    reviewer = ActorContext(
        actor_type="user",
        user_id="u-seller",
        acting_entity_id="entity-seller",
        auth_method="session",
        request_id="req-plan05-close",
    )
    case = review_service.open_case(
        conn,
        transaction_id=transaction_id,
        phase="settlement",
        source_type="video",
        source_id="video-source",
        reason_code="VIDEO_ADVISORY_ANOMALY",
        title="Video anomaly",
        description="Video advisory incelemesi gerekiyor.",
        severity="blocking",
        actor_context=ActorContext(actor_type="anonymous", auth_method="none"),
    )

    action = review_service.record_action(
        conn,
        case_id=case.id,
        actor_context=reviewer,
        action="escalate_dispute",
    )

    assert action.action.value == "escalate_dispute"
    assert action.payload["dispute_id"]
    dispute = disputes_service.get_dispute(conn, action.payload["dispute_id"])
    assert dispute.transaction_id == transaction_id
    assert dispute.status == "open"
    assert review_service.list_cases(conn, transaction_id)[0].status.value == "escalated"
    conn.close()


def test_review_endpoint_escalation_uses_participant_approver_authorization(
    tmp_path: Path,
) -> None:
    transaction_id = "tx-plan05-review-router"
    conn = make_db(tmp_path / "plan05-review-router.db")
    _prepare_account_transaction(conn, transaction_id)
    _add_real_memberships_and_approvers(conn, transaction_id)
    case = review_service.open_case(
        conn,
        transaction_id=transaction_id,
        phase="settlement",
        source_type="video",
        source_id="video-source",
        reason_code="VIDEO_ADVISORY_ANOMALY",
        title="Video anomaly",
        description="Video advisory incelemesi gerekiyor.",
        severity="blocking",
        actor_context=ActorContext(actor_type="anonymous", auth_method="none"),
    )
    conn.commit()

    platform_reviewer = ActorContext(
        actor_type="user",
        user_id="u-platform-reviewer",
        platform_role="reviewer",
        auth_method="session",
        request_id="req-plan05-review-router",
    )
    reviewer_response = TestClient(build_reviews_app(conn, platform_reviewer)).post(
        f"/api/reviews/{case.id}/actions", json={"action": "escalate_dispute"}
    )
    assert reviewer_response.status_code == 403

    participant_approver = ActorContext(
        actor_type="user",
        user_id="u-seller",
        acting_entity_id="entity-seller",
        auth_method="session",
        request_id="req-plan05-review-router",
    )
    approver_response = TestClient(build_reviews_app(conn, participant_approver)).post(
        f"/api/reviews/{case.id}/actions", json={"action": "escalate_dispute"}
    )
    assert approver_response.status_code == 200, approver_response.text
    assert approver_response.json()["action"] == "escalate_dispute"
    conn.close()


def test_real_app_plan05_evidence_and_dispute_guards(
    tmp_path: Path, monkeypatch
) -> None:
    """Gerçek session/CSRF/assignment akışı Plan 05 kapılarını birlikte doğrular.

    Ratification endpoint'i Plan 05'te yalnız `funding_pending` üretir; 015-017
    registry dışı bırakıldığı için `active` geçişi, Plan 05'te fonlanmış işlem
    fixture'ı olarak bu noktadan sonra bilinçli biçimde sağlanır.
    """
    db_path = tmp_path / "plan05-real-app.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(tmp_path / "documents"))

    conn = make_db(db_path)
    transaction_id = "tx-plan05-real-app"
    create_real_user(conn, email_normalized="real-plan05-buyer@example.com", user_id="u-buyer")
    create_real_user(conn, email_normalized="real-plan05-seller@example.com", user_id="u-seller")
    _create_entity(conn, "entity-buyer", "u-buyer")
    _create_entity(conn, "entity-seller", "u-seller")
    package_id = _setup_open_package(conn, transaction_id)
    _add_real_memberships_and_approvers(conn, transaction_id)
    buyer_session = create_real_session(conn, user_id="u-buyer")
    seller_session = create_real_session(conn, user_id="u-seller")
    conn.commit()
    conn.close()

    with TestClient(create_app()) as client:
        client.cookies.set("m4t_session", buyer_session.raw_token)
        buyer_ratification = client.post(
            f"/api/ratification-packages/{package_id}/ratifications",
            headers=_session_headers(buyer_session, "entity-buyer"),
        )
        assert buyer_ratification.status_code == 200, buyer_ratification.text

        client.cookies.clear()
        client.cookies.set("m4t_session", seller_session.raw_token)
        seller_ratification = client.post(
            f"/api/ratification-packages/{package_id}/ratifications",
            headers=_session_headers(seller_session, "entity-seller"),
        )
        assert seller_ratification.status_code == 200, seller_ratification.text
        assert seller_ratification.json()["funding_triggered"] is True

        premature_evidence = client.post(
            f"/api/transactions/{transaction_id}/evidence/e-irsaliye",
            json={"external_reference": "premature", "delivered_quantity": 10},
            headers=_session_headers(seller_session, "entity-seller"),
        )
        # Plan 06A cutover'ından sonra çift ratification işlemi gerçekten fonlar ve
        # `active`'e taşır; dolayısıyla erken evidence artık state guard'ına değil,
        # henüz enable edilmemiş takip policy guard'ına takılır (hâlâ 409).
        assert premature_evidence.status_code == 409
        assert premature_evidence.json()["code"] == "TRACKING_NOT_ENABLED"

    # Funding cutover Plan 06 kapsamıdır; Plan 05 adapter'ı yalnız active hesabı
    # tüketir ve account transaction'ı legacy `decided` durumuna yazamaz.
    conn = make_db(db_path)
    conn.execute("UPDATE transactions SET state = 'active' WHERE id = ?", (transaction_id,))
    conn.execute(
        "UPDATE tracking_policies SET manager_physical_delivery_confirmed = 1, "
        "tracking_mode = 'document_and_video', status = 'locked', locked_at = 'now' "
        "WHERE transaction_id = ?",
        (transaction_id,),
    )
    conn.commit()
    conn.close()

    with TestClient(create_app()) as client:
        client.cookies.set("m4t_session", seller_session.raw_token)
        evidence = client.post(
            f"/api/transactions/{transaction_id}/evidence/e-irsaliye",
            json={"external_reference": "accepted", "delivered_quantity": 10},
            headers=_session_headers(seller_session, "entity-seller"),
        )
        assert evidence.status_code == 200, evidence.text

        opened = client.post(
            f"/api/transactions/{transaction_id}/disputes",
            json={
                "reason_code": "QUALITY_ISSUE",
                "description": "Manuel inceleme gerekiyor.",
            },
            headers=_session_headers(seller_session, "entity-seller"),
        )
        assert opened.status_code == 200, opened.text
        dispute_id = opened.json()["id"]

        client.cookies.clear()
        client.cookies.set("m4t_session", buyer_session.raw_token)
        counterparty_resolve = client.post(
            f"/api/disputes/{dispute_id}/actions",
            json={"action": "resolve", "resolution_code": "NOT_AUTHORIZED"},
            headers=_session_headers(buyer_session, "entity-buyer"),
        )
        assert counterparty_resolve.status_code == 403
        assert counterparty_resolve.json()["code"] == "DISPUTE_RESOLVE_FORBIDDEN"

    conn = make_db(db_path)
    try:
        assert conn.execute(
            "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
        ).fetchone()[0] == "active"
    finally:
        conn.close()
