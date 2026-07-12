"""Plan 07 reconciliation matrisi testleri (services/payments/reconciliation.py)."""

from __future__ import annotations

import pytest

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.repositories import participants as participants_repo
from backend.app.repositories import provider_payments as provider_payments_repo
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from backend.app.services.payments import funding_coordinator
from backend.app.services.payments.domain import (
    PaymentDetailResult,
    ProviderOperationOutcome,
    ProviderPaymentDetail,
    ProviderPaymentIdentifier,
    ProviderPaymentStatus,
)
from backend.app.services.payments.ports import FakePaymentGateway
from backend.app.services.payments.reconciliation import reconcile_funding_unit

from test_plan06a_persistence import _seed_complete_package


@pytest.fixture()
def conn(tmp_path):
    connection = connect(Settings(db_path=tmp_path / "reconciliation.db"))
    init_db(connection)
    yield connection
    connection.close()


def _actor(user_id: str = "manager-recon") -> ActorContext:
    return ActorContext(
        actor_type="user",
        user_id=user_id,
        acting_entity_id="entity",
        auth_method="session",
        request_id="req-plan07-recon",
    )


def _funded_unit(conn):
    transaction_id, package_id = _seed_complete_package(conn)
    participants_repo.create_assignment(
        conn,
        transaction_id=transaction_id,
        participant_id=None,
        user_id="manager-recon",
        legal_entity_id="entity",
        role="manager",
    )
    gateway = FakePaymentGateway()
    result = funding_coordinator.ensure_pool_funded(
        conn, transaction_id, package_id, _actor(), gateway=gateway
    )
    assert result.status == "active"
    unit = conn.execute(
        "SELECT * FROM funding_units WHERE transaction_id = ? ORDER BY sequence LIMIT 1",
        (transaction_id,),
    ).fetchone()
    return transaction_id, unit, gateway


class _OverrideGateway(FakePaymentGateway):
    """get_payment_detail cevabını test senaryosuna göre override eden fake."""

    def __init__(self, base: FakePaymentGateway, detail):
        super().__init__(store=base._store)
        self._detail = detail

    def get_payment_detail(self, query):
        if callable(self._detail):
            return self._detail(query)
        return self._detail


def test_pool_creation_unknown_with_provider_pool_becomes_pool_created(conn) -> None:
    transaction_id, unit, gateway = _funded_unit(conn)
    assert unit["status"] == "pool_created"
    funding_units_repo.update_status(conn, unit["id"], "pool_creation_unknown")

    result = reconcile_funding_unit(
        conn, funding_unit_id=unit["id"], actor_context=_actor(), gateway=gateway
    )

    assert result.outcome == "pool_created"
    assert result.local_status == "pool_created"
    refreshed = funding_units_repo.get_by_id(conn, unit["id"])
    assert refreshed["status"] == "pool_created"


def test_approval_unknown_with_provider_approved_becomes_approved(conn) -> None:
    from backend.app.services.payments.release_coordinator import release_units

    transaction_id, unit, gateway = _funded_unit(conn)
    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=gateway,
        actor_context=_actor(),
    )
    approved_unit = funding_units_repo.get_by_id(conn, unit["id"])
    assert approved_unit["status"] == "approved"
    funding_units_repo.update_status(conn, unit["id"], "approval_unknown")

    result = reconcile_funding_unit(
        conn, funding_unit_id=unit["id"], actor_context=_actor(), gateway=gateway
    )

    assert result.outcome == "approved"
    refreshed = funding_units_repo.get_by_id(conn, unit["id"])
    assert refreshed["status"] == "approved"
    instruction = conn.execute(
        "SELECT status FROM release_instructions WHERE funding_unit_id = ? "
        "AND operation_type = 'approve_pool_payment'",
        (unit["id"],),
    ).fetchone()
    assert instruction["status"] == "confirmed"


def test_provider_refunded_marks_unit_refunded_regardless_of_local_state(conn) -> None:
    from backend.app.services.payments.release_coordinator import release_units

    transaction_id, unit, gateway = _funded_unit(conn)
    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=gateway,
        actor_context=_actor(),
    )
    provider_payment = provider_payments_repo.get_by_funding_unit(conn, unit["id"])
    identifier = ProviderPaymentIdentifier(
        virtual_pos_order_id=provider_payment["virtual_pos_order_id"],
        other_trx_code=provider_payment["other_trx_code"],
    )
    refund_result = gateway.refund_payment(identifier)
    assert refund_result.outcome is ProviderOperationOutcome.SUCCESS

    result = reconcile_funding_unit(
        conn, funding_unit_id=unit["id"], actor_context=_actor(), gateway=gateway
    )

    assert result.outcome == "refunded"
    refreshed = funding_units_repo.get_by_id(conn, unit["id"])
    assert refreshed["status"] == "refunded"


def test_not_found_with_pool_creation_unknown_is_retry_eligible(conn) -> None:
    transaction_id, unit, gateway = _funded_unit(conn)
    funding_units_repo.update_status(conn, unit["id"], "pool_creation_unknown")
    not_found_gateway = _OverrideGateway(
        gateway,
        PaymentDetailResult(
            outcome=ProviderOperationOutcome.FAILED,
            provider_code="PAYMENT_NOT_FOUND",
        ),
    )

    result = reconcile_funding_unit(
        conn, funding_unit_id=unit["id"], actor_context=_actor(), gateway=not_found_gateway
    )

    assert result.outcome == "retry_eligible"
    assert result.retry_eligible is True
    refreshed = funding_units_repo.get_by_id(conn, unit["id"])
    assert refreshed["status"] == "planned"


def test_provider_amount_drift_is_ambiguous_and_opens_review(conn) -> None:
    transaction_id, unit, gateway = _funded_unit(conn)
    funding_units_repo.update_status(conn, unit["id"], "pool_creation_unknown")
    drifted_gateway = _OverrideGateway(
        gateway,
        PaymentDetailResult(
            outcome=ProviderOperationOutcome.SUCCESS,
            payment=ProviderPaymentDetail(
                identifier=ProviderPaymentIdentifier(other_trx_code=unit["other_trx_code"]),
                amount_minor=int(unit["amount_minor"]) + 1,
                currency=unit["currency"],
                status=ProviderPaymentStatus.POOL,
                is_pool_payment=True,
            ),
        ),
    )
    assert not review_service.has_blocking_case(conn, transaction_id, phase="payment")

    result = reconcile_funding_unit(
        conn, funding_unit_id=unit["id"], actor_context=_actor(), gateway=drifted_gateway
    )

    assert result.outcome == "ambiguous"
    assert result.review_opened is True
    assert review_service.has_blocking_case(conn, transaction_id, phase="payment")
    refreshed = funding_units_repo.get_by_id(conn, unit["id"])
    assert refreshed["status"] == "pool_creation_unknown"


def test_provider_timeout_is_ambiguous_without_losing_local_state(conn) -> None:
    transaction_id, unit, gateway = _funded_unit(conn)
    funding_units_repo.update_status(conn, unit["id"], "approval_unknown")

    def _raise(query):
        raise TimeoutError("transport timeout")

    timeout_gateway = _OverrideGateway(gateway, _raise)

    result = reconcile_funding_unit(
        conn, funding_unit_id=unit["id"], actor_context=_actor(), gateway=timeout_gateway
    )

    assert result.outcome == "ambiguous"
    assert result.review_opened is True
    refreshed = funding_units_repo.get_by_id(conn, unit["id"])
    assert refreshed["status"] == "approval_unknown"
