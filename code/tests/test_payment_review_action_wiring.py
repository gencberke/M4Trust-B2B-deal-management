"""Faz 7 follow-up (§8) — review resolve action -> Berke'nin 7A payment
operation seam'i -> execution -> review case terminal resolution wiring.

`services/review.py::record_action`'a eklenen `_require_payment_operation_success_before_resolve`
precondition'ını egzersiz eder: `review.py`/`routers/reviews.py` provider'ı
DOĞRUDAN çağırmaz, yalnız Berke'nin `reconciliation.py`/`payment_operations.py`
fonksiyonlarını import edip sonucu yorumlar. Testler `Settings.from_env()`
default `PAYMENT_PROVIDER=mock` (SQLite-backed `FakePaymentGateway`) ile
tutarlı kalması için gateway'i HİÇBİR yerde explicit inject etmez -- funding,
release ve `execute_resolution`'ın kendi iç varsayılan gateway çözümü aynı
`conn`/store'u paylaşır."""

from __future__ import annotations

import pytest

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.repositories import participants as participants_repo
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from backend.app.services.payments import funding_coordinator, payment_operations
from backend.app.services.payments.domain import (
    PaymentDetailResult,
    ProviderOperationOutcome,
)
from backend.app.services.payments.release_coordinator import release_units

from test_plan06a_persistence import _seed_complete_package
from test_payment_operations import _actor, _attach_buyer_seller_approvers


@pytest.fixture()
def conn(tmp_path):
    connection = connect(Settings(db_path=tmp_path / "review-wiring.db"))
    init_db(connection)
    yield connection
    connection.close()


def _funded_unit(conn):
    """`_seed_complete_package` + gerçek funding/release -- HİÇBİR yerde
    explicit gateway inject etmez (varsayılan `PAYMENT_PROVIDER=mock` her
    çağrıda aynı SQLite-backed store'u paylaşsın diye)."""
    transaction_id, package_id = _seed_complete_package(conn)
    participants_repo.create_assignment(
        conn, transaction_id=transaction_id, participant_id=None,
        user_id="manager-07w", legal_entity_id="entity", role="manager",
    )
    result = funding_coordinator.ensure_pool_funded(
        conn, transaction_id, package_id, _actor("manager-07w"),
    )
    assert result.status == "active"
    default_gateway = funding_coordinator.make_payment_gateway(Settings.from_env(), conn)
    unit = conn.execute(
        "SELECT * FROM funding_units WHERE transaction_id = ? ORDER BY sequence LIMIT 1",
        (transaction_id,),
    ).fetchone()
    release_units(
        conn, transaction_id=transaction_id, unit_ids=(unit["id"],),
        gateway=default_gateway, actor_context=_actor("manager-07w"),
    )
    unit = funding_units_repo.get_by_id(conn, unit["id"])
    assert unit["status"] == "approved"
    return transaction_id, unit


def _find_case(conn, transaction_id: str, reason_code: str):
    cases = [
        case for case in review_service.list_cases(conn, transaction_id)
        if case.reason_code == reason_code
    ]
    assert len(cases) == 1, f"tek aktif {reason_code} case bekleniyordu, {len(cases)} bulundu"
    return cases[0]


def test_manager_cannot_resolve_undo_case_via_resolve_continue(conn) -> None:
    transaction_id, unit = _funded_unit(conn)
    payment_operations.request_resolution(
        conn, funding_unit_id=unit["id"], operation_type="undo_approval",
        actor_context=_actor("manager-07w"),
    )
    case = _find_case(conn, transaction_id, "PAYMENT_UNDO_REQUESTED")

    with pytest.raises(review_service.ReviewResolutionPreconditionError):
        review_service.record_action(
            conn, case_id=case.id, actor_context=_actor("manager-07w"),
            action="resolve_continue",
        )
    reopened = review_service.list_cases(conn, transaction_id)
    still_open = [c for c in reopened if c.id == case.id][0]
    assert still_open.status.value == "open"
    assert funding_units_repo.get_by_id(conn, unit["id"])["status"] == "approved"


def test_platform_reviewer_resolve_continue_executes_undo_and_resolves_case(conn) -> None:
    transaction_id, unit = _funded_unit(conn)
    payment_operations.request_resolution(
        conn, funding_unit_id=unit["id"], operation_type="undo_approval",
        actor_context=_actor("manager-07w"),
    )
    case = _find_case(conn, transaction_id, "PAYMENT_UNDO_REQUESTED")

    action = review_service.record_action(
        conn, case_id=case.id,
        actor_context=_actor("platform-07w", None, platform_role="reviewer"),
        action="resolve_continue",
    )
    assert action.action.value == "resolve_continue"
    resolved = [c for c in review_service.list_cases(conn, transaction_id) if c.id == case.id][0]
    assert resolved.status.value == "resolved"
    assert funding_units_repo.get_by_id(conn, unit["id"])["status"] == "approval_undone"


def test_bilateral_approval_allows_resolve_continue_to_execute_refund(conn) -> None:
    transaction_id, unit = _funded_unit(conn)
    _attach_buyer_seller_approvers(conn, transaction_id)
    resolution = payment_operations.request_resolution(
        conn, funding_unit_id=unit["id"], operation_type="refund",
        actor_context=_actor("manager-07w"),
    )
    payment_operations.approve_resolution(
        conn, resolution_id=resolution["id"],
        actor_context=_actor("buyer-approver-07", "entity-buyer-07"),
    )
    payment_operations.approve_resolution(
        conn, resolution_id=resolution["id"],
        actor_context=_actor("seller-approver-07", "entity-seller-07"),
    )
    case = _find_case(conn, transaction_id, "PAYMENT_REFUND_REQUESTED")

    # Bilateral onay tamamlandığı için execution herhangi bir authenticated
    # actor tarafından tetiklenebilir (manager DEĞİL -- burada da manager
    # kullanmıyoruz, buyer approver'ın kendisi tetikliyor).
    review_service.record_action(
        conn, case_id=case.id,
        actor_context=_actor("buyer-approver-07", "entity-buyer-07"),
        action="resolve_continue",
    )
    resolved = [c for c in review_service.list_cases(conn, transaction_id) if c.id == case.id][0]
    assert resolved.status.value == "resolved"
    assert funding_units_repo.get_by_id(conn, unit["id"])["status"] == "refunded"


class _AlwaysFailUndoGateway:
    """Yalnız undo_pool_approval'ı deterministik biçimde reddeden sarmalayıcı --
    provider tarafı hiçbir zaman başarıya ulaşmaz (case kapanmamalı)."""

    def __init__(self, delegate):
        self._delegate = delegate

    def create_pool_payment(self, command):
        return self._delegate.create_pool_payment(command)

    def approve_pool_payment(self, identifier):
        return self._delegate.approve_pool_payment(identifier)

    def undo_pool_approval(self, identifier):
        from backend.app.services.payments.domain import ProviderOperationResult

        return ProviderOperationResult(
            outcome=ProviderOperationOutcome.FAILED,
            identifier=identifier,
            provider_code="PAYMENT_UNDO_TEST_FAILURE",
            message="Deterministic test failure.",
        )

    def get_payment_detail(self, query):
        return self._delegate.get_payment_detail(query)


def test_resolve_continue_does_not_close_case_when_provider_execution_fails(
    conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    transaction_id, unit = _funded_unit(conn)
    payment_operations.request_resolution(
        conn, funding_unit_id=unit["id"], operation_type="undo_approval",
        actor_context=_actor("manager-07w"),
    )
    case = _find_case(conn, transaction_id, "PAYMENT_UNDO_REQUESTED")

    real_factory = funding_coordinator.make_payment_gateway

    def _failing_factory(settings, connection=None):
        return _AlwaysFailUndoGateway(real_factory(settings, connection))

    monkeypatch.setattr(
        "backend.app.services.payments.payment_operations.make_payment_gateway",
        _failing_factory,
    )

    with pytest.raises(review_service.ReviewResolutionPreconditionError):
        review_service.record_action(
            conn, case_id=case.id,
            actor_context=_actor("platform-07w", None, platform_role="reviewer"),
            action="resolve_continue",
        )
    still_open = [c for c in review_service.list_cases(conn, transaction_id) if c.id == case.id][0]
    assert still_open.status.value == "open"
    assert funding_units_repo.get_by_id(conn, unit["id"])["status"] == "approved"


class _UnknownDetailGateway:
    """`get_payment_detail` her zaman UNKNOWN döner -- reconciliation asla
    definitif sonuca ulaşamaz (persistent ambiguous senaryosu)."""

    def create_pool_payment(self, command):
        raise NotImplementedError

    def approve_pool_payment(self, identifier):
        raise NotImplementedError

    def undo_pool_approval(self, identifier):
        raise NotImplementedError

    def get_payment_detail(self, query):
        return PaymentDetailResult(outcome=ProviderOperationOutcome.UNKNOWN)


def test_resolve_continue_on_ambiguous_reconciliation_case_requires_definitive_result(
    conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Fonlama/release GERÇEK (varsayılan) gateway ile yapılır; ambiguous
    # senaryo yalnız BUNDAN SONRA monkeypatch ile devreye girer -- aksi halde
    # fixture kurulumu da kırılırdı.
    transaction_id, unit = _funded_unit(conn)

    real_factory = funding_coordinator.make_payment_gateway

    def _unknown_factory(settings, connection=None):
        return _UnknownDetailGateway()

    monkeypatch.setattr(
        "backend.app.services.payments.funding_coordinator.make_payment_gateway",
        _unknown_factory,
    )

    from backend.app.services.payments.reconciliation import reconcile_funding_unit

    first = reconcile_funding_unit(
        conn, funding_unit_id=unit["id"], actor_context=_actor("manager-07w"),
    )
    assert first.outcome == "ambiguous"
    case = _find_case(conn, transaction_id, "PAYMENT_RECONCILE_AMBIGUOUS")

    # record_action'ın precondition'ı reconcile_funding_unit'i TEKRAR çağırır;
    # gateway hâlâ patch'li (hâlâ UNKNOWN) -- case KAPANMAMALI.
    with pytest.raises(review_service.ReviewResolutionPreconditionError):
        review_service.record_action(
            conn, case_id=case.id,
            actor_context=_actor("platform-07w", None, platform_role="reviewer"),
            action="resolve_continue",
        )
    still_open = [c for c in review_service.list_cases(conn, transaction_id) if c.id == case.id][0]
    assert still_open.status.value == "open"

    # Gerçek gateway'e dönüldüğünde (provider'da kayıt gerçekten approved)
    # reconciliation artık definitif sonuca ulaşır ve case resolve edilebilir.
    monkeypatch.setattr(
        "backend.app.services.payments.funding_coordinator.make_payment_gateway",
        real_factory,
    )
    review_service.record_action(
        conn, case_id=case.id,
        actor_context=_actor("platform-07w", None, platform_role="reviewer"),
        action="resolve_continue",
    )
    resolved = [c for c in review_service.list_cases(conn, transaction_id) if c.id == case.id][0]
    assert resolved.status.value == "resolved"
