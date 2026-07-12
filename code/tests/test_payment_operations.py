"""Plan 07 reconciliation/retry/undo operation testleri."""

from __future__ import annotations

import pytest

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.repositories import participants as participants_repo
from backend.app.repositories import provider_payments as provider_payments_repo
from backend.app.services.access_control import ActorContext
from backend.app.services.account_lifecycle import AccountLifecycleError
from backend.app.services.payments import funding_coordinator, payment_operations
from backend.app.services.payments.domain import (
    ProviderOperationOutcome,
    ProviderOperationResult,
)
from backend.app.services.payments.ports import FakePaymentGateway

from test_plan06a_persistence import _seed_complete_package

_BUYER_ENTITY = "entity-buyer-07"
_SELLER_ENTITY = "entity-seller-07"


@pytest.fixture()
def conn(tmp_path):
    connection = connect(Settings(db_path=tmp_path / "payment-ops.db"))
    init_db(connection)
    yield connection
    connection.close()


def _actor(
    user_id: str,
    entity_id: str | None = "entity",
    *,
    platform_role: str | None = None,
) -> ActorContext:
    return ActorContext(
        actor_type="user",
        user_id=user_id,
        acting_entity_id=entity_id,
        platform_role=platform_role,
        auth_method="session",
        request_id="req-plan07",
    )


def _attach_buyer_seller_approvers(conn, transaction_id: str) -> None:
    import json as _json

    for role, entity_id, user_id in (
        ("buyer", _BUYER_ENTITY, "buyer-approver-07"),
        ("seller", _SELLER_ENTITY, "seller-approver-07"),
    ):
        participant_id = f"participant-{role}-07"
        conn.execute(
            """INSERT INTO transaction_participants (
                id, transaction_id, role, legal_entity_id, status,
                extracted_snapshot_json, declared_snapshot_json, confirmed_snapshot_json,
                confirmed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'confirmed', NULL, NULL, NULL, 'now', 'now', 'now')""",
            (participant_id, transaction_id, role, entity_id),
        )
        participants_repo.create_assignment(
            conn,
            transaction_id=transaction_id,
            participant_id=participant_id,
            user_id=user_id,
            legal_entity_id=entity_id,
            role="approver",
        )


class _NoRefundGateway:
    """PaymentGateway'i FakePaymentGateway'e delege eder ama refund_payment YOK.

    Gerçek Moka HTTP adapter'ının frozen contract'ında refund yüzeyi bulunmadığını
    simüle eder (bkz. Yusuf'un 9d4dfef refund contract freeze commit'i).
    """

    def __init__(self, delegate: FakePaymentGateway):
        self._delegate = delegate

    def create_pool_payment(self, command):
        return self._delegate.create_pool_payment(command)

    def approve_pool_payment(self, identifier):
        return self._delegate.approve_pool_payment(identifier)

    def undo_pool_approval(self, identifier):
        return self._delegate.undo_pool_approval(identifier)

    def get_payment_detail(self, query):
        return self._delegate.get_payment_detail(query)


def _funded_transaction(conn):
    transaction_id, package_id = _seed_complete_package(conn)
    participants_repo.create_assignment(
        conn,
        transaction_id=transaction_id,
        participant_id=None,
        user_id="manager-07",
        legal_entity_id="entity",
        role="manager",
    )
    gateway = FakePaymentGateway()
    # In-memory fake is enough for provider calls, while the coordinator's
    # SQLite store is used only when no gateway injection is provided.
    result = funding_coordinator.ensure_pool_funded(
        conn,
        transaction_id,
        package_id,
        _actor("manager-07"),
        gateway=gateway,
    )
    assert result.status == "active"
    unit = conn.execute(
        "SELECT * FROM funding_units WHERE transaction_id = ? ORDER BY sequence LIMIT 1",
        (transaction_id,),
    ).fetchone()
    provider_payment = provider_payments_repo.get_by_funding_unit(conn, unit["id"])
    return transaction_id, unit, provider_payment, gateway


def test_manager_can_request_but_cannot_execute_undo(conn) -> None:
    transaction_id, unit, provider_payment, gateway = _funded_transaction(conn)
    from backend.app.services.payments.release_coordinator import release_units

    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=gateway,
        actor_context=_actor("manager-07"),
    )
    resolution = payment_operations.request_resolution(
        conn,
        funding_unit_id=unit["id"],
        operation_type="undo_approval",
        actor_context=_actor("manager-07"),
    )
    with pytest.raises(payment_operations.PaymentOperationError):
        payment_operations.execute_resolution(
            conn,
            resolution_id=resolution["id"],
            actor_context=_actor("manager-07"),
            gateway=gateway,
        )


def test_reviewer_undo_is_idempotent_and_recomputes_state(conn) -> None:
    transaction_id, unit, provider_payment, gateway = _funded_transaction(conn)
    from backend.app.services.payments.release_coordinator import release_units

    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=gateway,
        actor_context=_actor("manager-07"),
    )
    resolution = payment_operations.request_resolution(
        conn,
        funding_unit_id=unit["id"],
        operation_type="undo_approval",
        actor_context=_actor("manager-07"),
        idempotency_key="undo:plan07:one",
    )
    first = payment_operations.execute_resolution(
        conn,
        resolution_id=resolution["id"],
        actor_context=_actor("platform-07", None, platform_role="reviewer"),
        gateway=gateway,
    )
    second = payment_operations.execute_resolution(
        conn,
        resolution_id=resolution["id"],
        actor_context=_actor("platform-07", None, platform_role="reviewer"),
        gateway=gateway,
    )
    assert first.status == second.status == "executed"
    assert conn.execute(
        "SELECT status FROM funding_units WHERE id = ?", (unit["id"],)
    ).fetchone()[0] == "approval_undone"
    assert conn.execute(
        "SELECT internal_status FROM provider_payments WHERE id = ?",
        (provider_payment["id"],),
    ).fetchone()[0] == "approval_undone"
    trace = payment_operations.get_payment_trace(conn, transaction_id)
    assert [item["operation_type"] for item in trace].count("undo_pool_approval") == 1
    serialized = str(trace)
    assert "Password" not in serialized
    assert "CardToken" not in serialized


def test_retry_reuses_instruction_and_increments_provider_attempt(conn) -> None:
    class FailOnceGateway(FakePaymentGateway):
        def __init__(self):
            super().__init__()
            self.approve_calls = 0

        def approve_pool_payment(self, identifier):
            self.approve_calls += 1
            if self.approve_calls == 1:
                return self._failed(identifier, "BANK_DECLINED", "safe test failure")
            return super().approve_pool_payment(identifier)

    failing_gateway = FailOnceGateway()
    transaction_id, package_id = _seed_complete_package(conn)
    participants_repo.create_assignment(
        conn,
        transaction_id=transaction_id,
        participant_id=None,
        user_id="manager-07",
        legal_entity_id="entity",
        role="manager",
    )
    result = funding_coordinator.ensure_pool_funded(
        conn,
        transaction_id,
        package_id,
        _actor("manager-07"),
        gateway=failing_gateway,
    )
    assert result.status == "active"
    unit = conn.execute(
        "SELECT * FROM funding_units WHERE transaction_id = ? ORDER BY sequence LIMIT 1",
        (transaction_id,),
    ).fetchone()
    from backend.app.services.payments.release_coordinator import release_units

    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=failing_gateway,
        actor_context=_actor("manager-07"),
    )
    instruction = conn.execute(
        "SELECT * FROM release_instructions WHERE funding_unit_id = ?",
        (unit["id"],),
    ).fetchone()
    assert instruction["status"] == "failed"
    first_key = instruction["idempotency_key"]

    retried = payment_operations.retry_release_instruction(
        conn,
        instruction_id=instruction["id"],
        actor_context=_actor("manager-07"),
        gateway=failing_gateway,
    )
    current = conn.execute(
        "SELECT * FROM release_instructions WHERE id = ?", (instruction["id"],)
    ).fetchone()
    operations = conn.execute(
        "SELECT * FROM provider_operations WHERE funding_unit_id = ? "
        "AND operation_type = 'approve_pool_payment' ORDER BY attempt_no",
        (unit["id"],),
    ).fetchall()
    assert retried["status"] == "confirmed"
    assert current["idempotency_key"] == first_key
    assert [row["attempt_no"] for row in operations] == [1, 2]
    assert conn.execute(
        "SELECT COUNT(*) FROM review_cases WHERE transaction_id = ? "
        "AND reason_code = 'PAYMENT_APPROVE_FAILED'",
        (transaction_id,),
    ).fetchone()[0] == 1


def test_single_party_cannot_execute_refund_but_bilateral_can(conn) -> None:
    transaction_id, unit, provider_payment, gateway = _funded_transaction(conn)
    from backend.app.services.payments.release_coordinator import release_units

    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=gateway,
        actor_context=_actor("manager-07"),
    )
    _attach_buyer_seller_approvers(conn, transaction_id)

    resolution = payment_operations.request_resolution(
        conn,
        funding_unit_id=unit["id"],
        operation_type="refund",
        actor_context=_actor("manager-07"),
    )
    payment_operations.approve_resolution(
        conn,
        resolution_id=resolution["id"],
        actor_context=_actor("buyer-approver-07", _BUYER_ENTITY),
    )
    only_buyer = payment_operations.resolutions_repo.get_by_id(conn, resolution["id"])
    assert only_buyer["status"] == "requested"
    with pytest.raises(payment_operations.PaymentOperationError):
        payment_operations.execute_resolution(
            conn,
            resolution_id=resolution["id"],
            actor_context=_actor("buyer-approver-07", _BUYER_ENTITY),
            gateway=gateway,
        )

    payment_operations.approve_resolution(
        conn,
        resolution_id=resolution["id"],
        actor_context=_actor("seller-approver-07", _SELLER_ENTITY),
    )
    authorized = payment_operations.resolutions_repo.get_by_id(conn, resolution["id"])
    assert authorized["status"] == "authorized"

    result = payment_operations.execute_resolution(
        conn,
        resolution_id=resolution["id"],
        actor_context=_actor("buyer-approver-07", _BUYER_ENTITY),
        gateway=gateway,
    )
    assert result.status == "executed"
    assert conn.execute(
        "SELECT status FROM funding_units WHERE id = ?", (unit["id"],)
    ).fetchone()[0] == "refunded"
    assert conn.execute(
        "SELECT internal_status FROM provider_payments WHERE id = ?",
        (provider_payment["id"],),
    ).fetchone()[0] == "refunded"


def test_refund_of_all_units_cancels_transaction(conn) -> None:
    from backend.app.services.payments.release_coordinator import release_units

    transaction_id, package_id = _seed_complete_package(conn)
    participants_repo.create_assignment(
        conn,
        transaction_id=transaction_id,
        participant_id=None,
        user_id="manager-07",
        legal_entity_id="entity",
        role="manager",
    )
    gateway = FakePaymentGateway()
    funding_coordinator.ensure_pool_funded(
        conn, transaction_id, package_id, _actor("manager-07"), gateway=gateway
    )
    units = conn.execute(
        "SELECT id FROM funding_units WHERE transaction_id = ? ORDER BY sequence",
        (transaction_id,),
    ).fetchall()
    assert len(units) == 2
    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=tuple(u["id"] for u in units),
        gateway=gateway,
        actor_context=_actor("manager-07"),
    )
    assert conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()[0] == "settled"

    for unit in units:
        resolution = payment_operations.request_resolution(
            conn,
            funding_unit_id=unit["id"],
            operation_type="refund",
            actor_context=_actor("manager-07"),
        )
        result = payment_operations.execute_resolution(
            conn,
            resolution_id=resolution["id"],
            actor_context=_actor("platform-07", None, platform_role="reviewer"),
            gateway=gateway,
        )
        assert result.status == "executed"

    refreshed_units = funding_units_repo.list_for_transaction(conn, transaction_id)
    assert {u["status"] for u in refreshed_units} == {"refunded"}
    assert conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()[0] == "cancelled"


def test_refund_without_gateway_capability_is_unsupported_and_opens_review(conn) -> None:
    transaction_id, unit, provider_payment, base_gateway = _funded_transaction(conn)
    from backend.app.services.payments.release_coordinator import release_units

    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=base_gateway,
        actor_context=_actor("manager-07"),
    )
    no_refund_gateway = _NoRefundGateway(base_gateway)

    resolution = payment_operations.request_resolution(
        conn,
        funding_unit_id=unit["id"],
        operation_type="refund",
        actor_context=_actor("manager-07"),
    )
    result = payment_operations.execute_resolution(
        conn,
        resolution_id=resolution["id"],
        actor_context=_actor("platform-07", None, platform_role="reviewer"),
        gateway=no_refund_gateway,
    )

    assert result.status == "failed"
    assert result.provider_code == "PAYMENT_REFUND_UNSUPPORTED"
    assert conn.execute(
        "SELECT status FROM funding_units WHERE id = ?", (unit["id"],)
    ).fetchone()[0] == "approved"
    assert conn.execute(
        "SELECT COUNT(*) FROM review_cases WHERE transaction_id = ? "
        "AND reason_code = 'PAYMENT_REFUND_FAILED'",
        (transaction_id,),
    ).fetchone()[0] == 1


# --- Review remediation regression tests (BOLA / unknown recovery / atomic claim / lifecycle drift) ---


def test_unrelated_authenticated_user_cannot_execute_bilateral_resolution(conn) -> None:
    transaction_id, unit, provider_payment, gateway = _funded_transaction(conn)
    from backend.app.services.payments.release_coordinator import release_units

    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=gateway,
        actor_context=_actor("manager-07"),
    )
    _attach_buyer_seller_approvers(conn, transaction_id)
    resolution = payment_operations.request_resolution(
        conn,
        funding_unit_id=unit["id"],
        operation_type="undo_approval",
        actor_context=_actor("manager-07"),
    )
    payment_operations.approve_resolution(
        conn, resolution_id=resolution["id"],
        actor_context=_actor("buyer-approver-07", _BUYER_ENTITY),
    )
    payment_operations.approve_resolution(
        conn, resolution_id=resolution["id"],
        actor_context=_actor("seller-approver-07", _SELLER_ENTITY),
    )

    class BoomGateway(FakePaymentGateway):
        def undo_pool_approval(self, identifier):
            raise AssertionError("provider ilgisiz kullanıcı için çağrılmamalıydı")

    with pytest.raises(payment_operations.PaymentOperationError):
        payment_operations.execute_resolution(
            conn,
            resolution_id=resolution["id"],
            actor_context=_actor("random-stranger-99", "unrelated-entity-99"),
            gateway=BoomGateway(),
        )
    assert conn.execute(
        "SELECT status FROM payment_resolutions WHERE id = ?", (resolution["id"],)
    ).fetchone()[0] == "authorized"


def test_execute_resolution_atomic_claim_rejects_concurrent_call(conn) -> None:
    transaction_id, unit, provider_payment, gateway = _funded_transaction(conn)
    from backend.app.services.payments.release_coordinator import release_units

    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=gateway,
        actor_context=_actor("manager-07"),
    )
    resolution = payment_operations.request_resolution(
        conn,
        funding_unit_id=unit["id"],
        operation_type="undo_approval",
        actor_context=_actor("manager-07"),
    )
    # Başka bir worker/process aynı resolution'ı zaten claim etmiş gibi simüle eder.
    claimed = payment_operations.resolutions_repo.claim_executing(
        conn, resolution["id"], from_statuses=("requested", "authorized")
    )
    assert claimed is True

    class BoomGateway(FakePaymentGateway):
        def undo_pool_approval(self, identifier):
            raise AssertionError("provider ikinci (kaybeden) çağrı için çağrılmamalıydı")

    with pytest.raises(payment_operations.PaymentOperationError):
        payment_operations.execute_resolution(
            conn,
            resolution_id=resolution["id"],
            actor_context=_actor("platform-07", None, platform_role="reviewer"),
            gateway=BoomGateway(),
        )
    assert conn.execute(
        "SELECT status FROM payment_resolutions WHERE id = ?", (resolution["id"],)
    ).fetchone()[0] == "executing"


def test_undo_unknown_after_provider_success_reconciles_to_executed(conn) -> None:
    transaction_id, unit, provider_payment, gateway = _funded_transaction(conn)
    from backend.app.services.payments.release_coordinator import release_units

    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=gateway,
        actor_context=_actor("manager-07"),
    )
    conn.execute("UPDATE transactions SET state = 'settled' WHERE id = ?", (transaction_id,))
    conn.commit()

    class TimeoutAfterCommitGateway(FakePaymentGateway):
        def undo_pool_approval(self, identifier):
            result = super().undo_pool_approval(identifier)
            if result.outcome is ProviderOperationOutcome.SUCCESS:
                return ProviderOperationResult(
                    outcome=ProviderOperationOutcome.UNKNOWN, identifier=identifier
                )
            return result

    timeout_gateway = TimeoutAfterCommitGateway(store=gateway._store)
    resolution = payment_operations.request_resolution(
        conn,
        funding_unit_id=unit["id"],
        operation_type="undo_approval",
        actor_context=_actor("manager-07"),
    )

    first = payment_operations.execute_resolution(
        conn,
        resolution_id=resolution["id"],
        actor_context=_actor("platform-07", None, platform_role="reviewer"),
        gateway=timeout_gateway,
    )
    assert first.status == "unknown"
    assert conn.execute(
        "SELECT status FROM payment_resolutions WHERE id = ?", (resolution["id"],)
    ).fetchone()[0] == "unknown"

    second = payment_operations.execute_resolution(
        conn,
        resolution_id=resolution["id"],
        actor_context=_actor("platform-07", None, platform_role="reviewer"),
        gateway=timeout_gateway,
    )
    assert second.status == "executed"
    assert conn.execute(
        "SELECT status FROM funding_units WHERE id = ?", (unit["id"],)
    ).fetchone()[0] == "approval_undone"
    assert conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()[0] == "active"
    ops = conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE funding_unit_id = ? "
        "AND operation_type = 'undo_pool_approval'",
        (unit["id"],),
    ).fetchone()[0]
    assert ops == 1


def test_refund_unknown_after_provider_success_reconciles_to_executed(conn) -> None:
    transaction_id, unit, provider_payment, gateway = _funded_transaction(conn)
    from backend.app.services.payments.release_coordinator import release_units

    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=gateway,
        actor_context=_actor("manager-07"),
    )

    class TimeoutAfterCommitGateway(FakePaymentGateway):
        def refund_payment(self, identifier):
            result = super().refund_payment(identifier)
            if result.outcome is ProviderOperationOutcome.SUCCESS:
                return ProviderOperationResult(
                    outcome=ProviderOperationOutcome.UNKNOWN, identifier=identifier
                )
            return result

    timeout_gateway = TimeoutAfterCommitGateway(store=gateway._store)
    resolution = payment_operations.request_resolution(
        conn,
        funding_unit_id=unit["id"],
        operation_type="refund",
        actor_context=_actor("manager-07"),
    )

    first = payment_operations.execute_resolution(
        conn,
        resolution_id=resolution["id"],
        actor_context=_actor("platform-07", None, platform_role="reviewer"),
        gateway=timeout_gateway,
    )
    assert first.status == "unknown"

    second = payment_operations.execute_resolution(
        conn,
        resolution_id=resolution["id"],
        actor_context=_actor("platform-07", None, platform_role="reviewer"),
        gateway=timeout_gateway,
    )
    assert second.status == "executed"
    assert conn.execute(
        "SELECT status FROM funding_units WHERE id = ?", (unit["id"],)
    ).fetchone()[0] == "refunded"
    ops = conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE funding_unit_id = ? "
        "AND operation_type = 'refund'",
        (unit["id"],),
    ).fetchone()[0]
    assert ops == 1


def test_lifecycle_transition_failure_does_not_report_success(conn, monkeypatch) -> None:
    transaction_id, unit, provider_payment, gateway = _funded_transaction(conn)
    from backend.app.services.payments.release_coordinator import release_units

    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=gateway,
        actor_context=_actor("manager-07"),
    )
    conn.execute("UPDATE transactions SET state = 'settled' WHERE id = ?", (transaction_id,))
    conn.commit()

    resolution = payment_operations.request_resolution(
        conn,
        funding_unit_id=unit["id"],
        operation_type="undo_approval",
        actor_context=_actor("manager-07"),
    )

    def _boom(*args, **kwargs):
        raise AccountLifecycleError("simulated lifecycle transition failure")

    monkeypatch.setattr(payment_operations, "transition_account_state", _boom)

    result = payment_operations.execute_resolution(
        conn,
        resolution_id=resolution["id"],
        actor_context=_actor("platform-07", None, platform_role="reviewer"),
        gateway=gateway,
    )

    assert result.status == "unknown"
    assert result.provider_code == "PAYMENT_LIFECYCLE_TRANSITION_FAILED"
    # Provider side effect (irreversible) local olarak korunur:
    assert conn.execute(
        "SELECT status FROM funding_units WHERE id = ?", (unit["id"],)
    ).fetchone()[0] == "approval_undone"
    assert conn.execute(
        "SELECT internal_status FROM provider_payments WHERE id = ?",
        (provider_payment["id"],),
    ).fetchone()[0] == "approval_undone"
    # Ama resolution 'executed' DEĞİL -- API tam başarı bildirmez, case açık kalır.
    assert conn.execute(
        "SELECT status FROM payment_resolutions WHERE id = ?", (resolution["id"],)
    ).fetchone()[0] == "unknown"
    assert conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()[0] == "settled"


def test_successful_retry_resolves_payment_approve_failed_case(conn) -> None:
    class FailOnceGateway(FakePaymentGateway):
        def __init__(self):
            super().__init__()
            self.approve_calls = 0

        def approve_pool_payment(self, identifier):
            self.approve_calls += 1
            if self.approve_calls == 1:
                return self._failed(identifier, "BANK_DECLINED", "safe test failure")
            return super().approve_pool_payment(identifier)

    failing_gateway = FailOnceGateway()
    transaction_id, package_id = _seed_complete_package(conn)
    participants_repo.create_assignment(
        conn,
        transaction_id=transaction_id,
        participant_id=None,
        user_id="manager-07",
        legal_entity_id="entity",
        role="manager",
    )
    result = funding_coordinator.ensure_pool_funded(
        conn, transaction_id, package_id, _actor("manager-07"), gateway=failing_gateway,
    )
    assert result.status == "active"
    unit = conn.execute(
        "SELECT * FROM funding_units WHERE transaction_id = ? ORDER BY sequence LIMIT 1",
        (transaction_id,),
    ).fetchone()
    from backend.app.services.payments.release_coordinator import release_units

    release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=(unit["id"],),
        gateway=failing_gateway,
        actor_context=_actor("manager-07"),
    )
    assert conn.execute(
        "SELECT status FROM review_cases WHERE transaction_id = ? AND reason_code = 'PAYMENT_APPROVE_FAILED'",
        (transaction_id,),
    ).fetchone()[0] == "open"

    instruction = conn.execute(
        "SELECT * FROM release_instructions WHERE funding_unit_id = ?", (unit["id"],),
    ).fetchone()
    payment_operations.retry_release_instruction(
        conn,
        instruction_id=instruction["id"],
        actor_context=_actor("manager-07"),
        gateway=failing_gateway,
    )

    case_status = conn.execute(
        "SELECT status, resolution_code FROM review_cases WHERE transaction_id = ? "
        "AND reason_code = 'PAYMENT_APPROVE_FAILED'",
        (transaction_id,),
    ).fetchone()
    assert case_status["status"] == "resolved"
    assert case_status["resolution_code"] == "RETRY_PAYMENT_AUTHORIZED"
