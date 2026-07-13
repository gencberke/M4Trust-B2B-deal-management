"""Faz 7B — payment failure -> review kontratı ve authorization kontratı testleri.

Kapsam: `services/review.py`'e Plan 07'de eklenen `open_payment_review_case`,
reason/resolution-code sabitleri, authorization predicate'leri ve saf
`BilateralResolutionState` state machine'i. Gerçek `payment_resolutions`
seam'i (Berke'nin 7A'sı) henüz yok -- bilateral testler saf state machine'i
egzersiz eder, DB'ye dokunmaz.
"""

from __future__ import annotations

import sqlite3
from importlib import import_module
from uuid import uuid4

import pytest

from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from reviews_fixtures import create_real_user

_lifecycle_migration = import_module("backend.app.db.migrations.007_transaction_lifecycle_v2")


def make_full_reviews_db() -> sqlite3.Connection:
    """`reviews_fixtures.make_full_reviews_db()` + 007 (`lifecycle_version` kolonu) --
    payment review case'leri account_v2 transaction'ları üzerinde açılır."""
    from reviews_fixtures import make_full_reviews_db as _base

    conn = _base()
    _lifecycle_migration.apply(conn)
    conn.commit()
    return conn


def _actor(user_id: str | None, entity_id: str | None = None, *, platform_role: str | None = None) -> ActorContext:
    return ActorContext(
        actor_type="user" if user_id else "anonymous",
        user_id=user_id,
        acting_entity_id=entity_id,
        platform_role=platform_role,
        auth_method="session" if user_id else "none",
    )


def _create_entity(conn, entity_id: str, user_id: str) -> None:
    conn.execute(
        "INSERT INTO legal_entities (id, entity_type, legal_name, tax_identifier_type, "
        "tax_identifier_ciphertext, tax_identifier_lookup_hmac, tax_identifier_last4, "
        "verification_status, created_by_user_id, created_at, updated_at) "
        "VALUES (?, 'company', ?, 'vkn', 'cipher', ?, '1234', 'self_declared', ?, 'now', 'now')",
        (entity_id, entity_id, entity_id, user_id),
    )


def _seed_manager_and_approvers(conn, tx_id: str) -> dict[str, str]:
    """manager + buyer approver + seller approver assignment'ları olan bir
    transaction kurar. Dönen dict: {"manager": user_id, "buyer": user_id, "seller": user_id}."""
    from backend.app.repositories import participants as participants_repo

    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES (?, 'active', NULL, NULL, NULL, NULL, NULL, 'now', 'account_v2', 'entity-buyer')",
        (tx_id,),
    )
    users = {
        "manager": create_real_user(conn, email_normalized=f"{tx_id}-mgr@example.com"),
        "buyer": create_real_user(conn, email_normalized=f"{tx_id}-buyer@example.com"),
        "seller": create_real_user(conn, email_normalized=f"{tx_id}-seller@example.com"),
        "outsider": create_real_user(conn, email_normalized=f"{tx_id}-outsider@example.com"),
    }
    _create_entity(conn, "entity-buyer", users["buyer"])
    _create_entity(conn, "entity-seller", users["seller"])

    buyer_participant_id = uuid4().hex
    seller_participant_id = uuid4().hex
    conn.execute(
        "INSERT INTO transaction_participants "
        "(id, transaction_id, role, legal_entity_id, status, created_at, updated_at) "
        "VALUES (?, ?, 'buyer', 'entity-buyer', 'confirmed', 'now', 'now')",
        (buyer_participant_id, tx_id),
    )
    conn.execute(
        "INSERT INTO transaction_participants "
        "(id, transaction_id, role, legal_entity_id, status, created_at, updated_at) "
        "VALUES (?, ?, 'seller', 'entity-seller', 'confirmed', 'now', 'now')",
        (seller_participant_id, tx_id),
    )
    participants_repo.create_assignment(
        conn, transaction_id=tx_id, participant_id=None, user_id=users["manager"],
        legal_entity_id="entity-buyer", role="manager",
    )
    participants_repo.create_assignment(
        conn, transaction_id=tx_id, participant_id=buyer_participant_id, user_id=users["buyer"],
        legal_entity_id="entity-buyer", role="approver",
    )
    participants_repo.create_assignment(
        conn, transaction_id=tx_id, participant_id=seller_participant_id, user_id=users["seller"],
        legal_entity_id="entity-seller", role="approver",
    )
    conn.commit()
    return users


# --- Failure -> review kontratı --------------------------------------------


def test_same_payment_failure_does_not_open_duplicate_active_case() -> None:
    conn = make_full_reviews_db()
    users = _seed_manager_and_approvers(conn, "tx-payment-1")
    actor = _actor(users["manager"])

    first = review_service.open_payment_review_case(
        conn, transaction_id="tx-payment-1", funding_unit_id="unit-1",
        reason_code=review_service.PAYMENT_POOL_CREATION_FAILED,
        title="Pool oluşturma başarısız", description="Funding unit provider pool durumuna ulaşamadı.",
        actor_context=actor,
    )
    second = review_service.open_payment_review_case(
        conn, transaction_id="tx-payment-1", funding_unit_id="unit-1",
        reason_code=review_service.PAYMENT_POOL_CREATION_FAILED,
        title="Pool oluşturma başarısız", description="Funding unit provider pool durumuna ulaşamadı.",
        actor_context=actor,
    )
    assert first.id == second.id
    count = conn.execute(
        "SELECT COUNT(*) FROM review_cases WHERE transaction_id = ?", ("tx-payment-1",)
    ).fetchone()[0]
    assert count == 1


def test_reason_code_and_source_id_contract_is_stable() -> None:
    conn = make_full_reviews_db()
    users = _seed_manager_and_approvers(conn, "tx-payment-2")
    case = review_service.open_payment_review_case(
        conn, transaction_id="tx-payment-2", funding_unit_id="unit-42",
        reason_code=review_service.PAYMENT_APPROVE_FAILED,
        title="Approve başarısız", description="Approve isteği definitive failure ile sonuçlandı.",
        actor_context=_actor(users["manager"]),
    )
    assert case.phase.value == "payment"
    assert case.source_type.value == "payment"
    assert case.severity.value == "blocking"
    assert case.source_id == "unit-42"
    assert case.reason_code == review_service.PAYMENT_APPROVE_FAILED


def test_unknown_reason_code_rejected() -> None:
    conn = make_full_reviews_db()
    users = _seed_manager_and_approvers(conn, "tx-payment-3")
    with pytest.raises(review_service.PaymentReviewReasonCodeError):
        review_service.open_payment_review_case(
            conn, transaction_id="tx-payment-3", funding_unit_id="unit-1",
            reason_code="PAYMENT_MADE_UP_CODE",
            title="x", description="y",
            actor_context=_actor(users["manager"]),
        )


def test_all_mandatory_reason_codes_open_distinct_cases() -> None:
    conn = make_full_reviews_db()
    users = _seed_manager_and_approvers(conn, "tx-payment-4")
    actor = _actor(users["manager"])
    for reason_code in sorted(review_service.PAYMENT_REASON_CODES):
        case = review_service.open_payment_review_case(
            conn, transaction_id="tx-payment-4", funding_unit_id="unit-1",
            reason_code=reason_code, title="Ödeme sorunu", description="Deterministik açıklama.",
            actor_context=actor,
        )
        assert case.reason_code == reason_code
    count = conn.execute(
        "SELECT COUNT(*) FROM review_cases WHERE transaction_id = ?", ("tx-payment-4",)
    ).fetchone()[0]
    assert count == len(review_service.PAYMENT_REASON_CODES)


def test_raw_secret_like_description_rejected() -> None:
    conn = make_full_reviews_db()
    users = _seed_manager_and_approvers(conn, "tx-payment-5")
    token_like = "aB3dE5fG7hJ9kL1mN3oP5qR7sT9u"  # 28 char opak token benzeri
    with pytest.raises(review_service.ReviewCommentRejectedError):
        review_service.open_payment_review_case(
            conn, transaction_id="tx-payment-5", funding_unit_id="unit-1",
            reason_code=review_service.PAYMENT_RECONCILE_AMBIGUOUS,
            title="Reconcile belirsiz", description=f"Provider trace: {token_like}",
            actor_context=_actor(users["manager"]),
        )


# --- Authorization kontratı --------------------------------------------------


def test_manager_can_request_reconciliation() -> None:
    conn = make_full_reviews_db()
    users = _seed_manager_and_approvers(conn, "tx-auth-1")
    assert review_service.can_request_payment_reconciliation(
        conn, "tx-auth-1", _actor(users["manager"], "entity-buyer")
    )


def test_manager_can_request_retry() -> None:
    conn = make_full_reviews_db()
    users = _seed_manager_and_approvers(conn, "tx-auth-2")
    assert review_service.can_request_payment_retry(
        conn, "tx-auth-2", _actor(users["manager"], "entity-buyer")
    )


def test_manager_cannot_execute_undo_or_refund() -> None:
    conn = make_full_reviews_db()
    users = _seed_manager_and_approvers(conn, "tx-auth-3")
    manager_actor = _actor(users["manager"], "entity-buyer")
    assert review_service.can_request_payment_reversal(conn, "tx-auth-3", manager_actor)
    # Execution: manager platform reviewer değil ve bilateral resolution tamamlanmadı.
    authorized = review_service.can_authorize_payment_reversal(
        is_platform_reviewer=review_service.is_platform_reviewer_or_admin(manager_actor),
        bilateral_resolution_complete=False,
    )
    assert authorized is False


def test_platform_reviewer_can_authorize_undo_or_refund() -> None:
    reviewer_actor = _actor(user_id="reviewer-1", platform_role="reviewer")
    authorized = review_service.can_authorize_payment_reversal(
        is_platform_reviewer=review_service.is_platform_reviewer_or_admin(reviewer_actor),
        bilateral_resolution_complete=False,
    )
    assert authorized is True


def test_outsider_is_not_transaction_manager() -> None:
    conn = make_full_reviews_db()
    users = _seed_manager_and_approvers(conn, "tx-auth-4")
    assert not review_service.is_transaction_manager(conn, "tx-auth-4", _actor(users["outsider"]))
    assert not review_service.can_request_payment_reconciliation(
        conn, "tx-auth-4", _actor(users["outsider"])
    )


# --- Bilateral resolution (saf state machine) --------------------------------


def test_buyer_alone_cannot_complete_bilateral_resolution() -> None:
    state = review_service.BilateralResolutionState(
        buyer_entity_id="entity-buyer", seller_entity_id="entity-seller"
    )
    state = state.record_approval(role="buyer", user_id="u-buyer", entity_id="entity-buyer")
    assert state.is_complete is False


def test_seller_alone_cannot_complete_bilateral_resolution() -> None:
    state = review_service.BilateralResolutionState(
        buyer_entity_id="entity-buyer", seller_entity_id="entity-seller"
    )
    state = state.record_approval(role="seller", user_id="u-seller", entity_id="entity-seller")
    assert state.is_complete is False


def test_buyer_and_seller_together_complete_resolution() -> None:
    state = review_service.BilateralResolutionState(
        buyer_entity_id="entity-buyer", seller_entity_id="entity-seller"
    )
    state = state.record_approval(role="buyer", user_id="u-buyer", entity_id="entity-buyer")
    state = state.record_approval(role="seller", user_id="u-seller", entity_id="entity-seller")
    assert state.is_complete is True
    authorized = review_service.can_authorize_payment_reversal(
        is_platform_reviewer=False, bilateral_resolution_complete=state.is_complete
    )
    assert authorized is True


def test_same_party_cannot_approve_twice() -> None:
    state = review_service.BilateralResolutionState(
        buyer_entity_id="entity-buyer", seller_entity_id="entity-seller"
    )
    state = state.record_approval(role="buyer", user_id="u-buyer", entity_id="entity-buyer")
    with pytest.raises(review_service.BilateralApprovalRejectedError):
        state.record_approval(role="buyer", user_id="u-buyer-2", entity_id="entity-buyer")


def test_wrong_entity_approval_rejected() -> None:
    state = review_service.BilateralResolutionState(
        buyer_entity_id="entity-buyer", seller_entity_id="entity-seller"
    )
    with pytest.raises(review_service.BilateralApprovalRejectedError):
        state.record_approval(role="buyer", user_id="u-imposter", entity_id="entity-seller")


def test_is_payment_resolution_approver_identifies_buyer_and_seller_roles() -> None:
    conn = make_full_reviews_db()
    users = _seed_manager_and_approvers(conn, "tx-auth-5")
    assert review_service.is_payment_resolution_approver(
        conn, "tx-auth-5", _actor(users["buyer"], "entity-buyer")
    ) == "buyer"
    assert review_service.is_payment_resolution_approver(
        conn, "tx-auth-5", _actor(users["seller"], "entity-seller")
    ) == "seller"
    assert review_service.is_payment_resolution_approver(
        conn, "tx-auth-5", _actor(users["manager"], None)
    ) is None
