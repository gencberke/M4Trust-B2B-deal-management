"""Funding-unit/provider reconciliation (Plan 07 / Moka §16).

Detail sorgusu yalnız OtherTrxCode ile yapılır. Provider cevabı local funding
unit kimliğiyle fail-closed bağlanamıyorsa local state korunur ve blocking
payment review açılır; provider unknown sonucu definitive failure değildir.
"""

from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection
from uuid import uuid4

from backend.app.config import Settings
from backend.app.eventbus import emit
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.repositories import milestones as milestones_repo
from backend.app.repositories import provider_payments as provider_payments_repo
from backend.app.repositories import release_instructions as release_instructions_repo
from backend.app.services import audit
from backend.app.services import processing_jobs
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from backend.app.services.account_lifecycle import (
    AccountLifecycleError,
    transition_account_state,
)
from backend.app.services.payments.domain import (
    PaymentDetailQuery,
    ProviderOperationOutcome,
    ProviderPaymentIdentifier,
    ProviderPaymentStatus,
)
from backend.app.services.payments.ports import PaymentGateway

_APPROVE_OPERATION = "approve_pool_payment"
_NOT_FOUND_CODES = frozenset({"PAYMENT_NOT_FOUND", "PROVIDER_PAYMENT_NOT_FOUND"})


class ReconciliationError(ValueError):
    """Reconciliation input/consistency hatası."""


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    funding_unit_id: str
    outcome: str
    local_status: str
    provider_status: str | None = None
    retry_eligible: bool = False
    review_opened: bool = False
    provider_payment_id: str | None = None

    @property
    def status(self) -> str:
        """Compatibility alias: outcome reconciliation status'ıdır."""

        return self.outcome


def _actor_for_audit(actor: ActorContext) -> audit.AuditActor:
    return audit.AuditActor(
        actor_type="user" if actor.user_id else "system",
        user_id=actor.user_id,
        acting_entity_id=actor.acting_entity_id,
        request_id=actor.request_id,
    )


def _open_ambiguous_review(
    conn: Connection,
    *,
    unit,
    actor_context: ActorContext,
    reason_code: str = "PAYMENT_RECONCILE_AMBIGUOUS",
) -> bool:
    before = review_service.has_blocking_case(conn, unit["transaction_id"], phase="payment")
    review_service.open_case(
        conn,
        transaction_id=unit["transaction_id"],
        phase="payment",
        source_type="payment",
        source_id=unit["id"],
        reason_code=reason_code,
        title="Provider ödeme durumu yerel kayıtla eşleşmiyor",
        description="Moka detail cevabı güvenli biçimde funding unit'e bağlanamadı.",
        severity="blocking",
        actor_context=actor_context,
    )
    return not before or review_service.has_blocking_case(
        conn, unit["transaction_id"], phase="payment"
    )


def _safe_provider_detail(gateway: PaymentGateway, unit):
    try:
        return gateway.get_payment_detail(
            query=PaymentDetailQuery(
                identifier=ProviderPaymentIdentifier(other_trx_code=unit["other_trx_code"])
            )
        )
    except Exception:
        return None


def _identifier_matches(unit, provider_payment, local_payment) -> bool:
    identifier = provider_payment.identifier
    if identifier.other_trx_code != unit["other_trx_code"]:
        return False
    if (
        local_payment is not None
        and local_payment["virtual_pos_order_id"]
        and identifier.virtual_pos_order_id
        and local_payment["virtual_pos_order_id"] != identifier.virtual_pos_order_id
    ):
        return False
    if provider_payment.amount_minor is not None and int(provider_payment.amount_minor) != int(
        unit["amount_minor"]
    ):
        return False
    if provider_payment.currency is not None and str(provider_payment.currency) != str(
        unit["currency"]
    ):
        return False
    return provider_payment.is_pool_payment


def _bind_provider_payment(
    conn: Connection,
    *,
    unit,
    provider_payment,
    internal_status: str,
    existing_payment,
):
    return provider_payments_repo.upsert_payment(
        conn,
        payment_id=existing_payment["id"] if existing_payment is not None else uuid4().hex,
        funding_unit_id=unit["id"],
        provider_profile=unit["provider_profile"],
        other_trx_code=unit["other_trx_code"],
        virtual_pos_order_id=provider_payment.identifier.virtual_pos_order_id,
        amount_minor=unit["amount_minor"],
        currency=unit["currency"],
        internal_status=internal_status,
    )


def _ensure_approve_instruction(conn: Connection, *, unit, payment):
    instruction = release_instructions_repo.get_by_unit_and_operation(
        conn, funding_unit_id=unit["id"], operation_type=_APPROVE_OPERATION
    )
    if instruction is None:
        instruction = release_instructions_repo.insert(
            conn,
            funding_unit_id=unit["id"],
            provider_payment_id=payment["id"],
            idempotency_key=f"funding-unit:{unit['id']}:{_APPROVE_OPERATION}",
            amount_minor=unit["amount_minor"],
            currency=unit["currency"],
            provider=unit["provider_profile"],
            provider_reference=payment["virtual_pos_order_id"],
        )
    return instruction


def _recompute_aggregates(conn: Connection, transaction_id: str) -> None:
    for milestone in milestones_repo.list_for_transaction(conn, transaction_id):
        units = funding_units_repo.list_for_milestone(conn, milestone["id"])
        released = sum(int(unit["amount_minor"]) for unit in units if unit["status"] == "approved")
        total = int(milestone["amount_minor"])
        if released >= total:
            status = "released"
        elif released > 0:
            status = "partially_released"
        elif milestone["status"] not in {"cancelled", "disputed"}:
            status = "pending"
        else:
            status = milestone["status"]
        if (
            int(milestone["released_amount_minor"]) != released
            or milestone["status"] != status
        ):
            milestones_repo.update_released_amount(
                conn,
                milestone["id"],
                released_amount_minor=released,
                status=status,
            )


def _settle_if_complete(conn: Connection, *, transaction_id: str, actor_context: ActorContext) -> None:
    milestones = milestones_repo.list_for_transaction(conn, transaction_id)
    if not milestones or not all(m["status"] == "released" for m in milestones):
        return
    try:
        transitioned = transition_account_state(
            conn,
            transaction_id=transaction_id,
            expected_states={"active"},
            target_state="settled",
            actor_context=actor_context,
            reason_code="ALL_MILESTONES_RELEASED",
        )
    except AccountLifecycleError:
        return
    if transitioned:
        emit(
            conn,
            transaction_id,
            "transaction_settled",
            {"milestone_count": len(milestones)},
            "payment_reconciliation",
        )


def _result(
    conn: Connection,
    *,
    unit_id: str,
    outcome: str,
    provider_status: str | None,
    retry_eligible: bool = False,
    review_opened: bool = False,
    provider_payment_id: str | None = None,
) -> ReconciliationResult:
    unit = funding_units_repo.get_by_id(conn, unit_id)
    return ReconciliationResult(
        funding_unit_id=unit_id,
        outcome=outcome,
        local_status=unit["status"] if unit is not None else "missing",
        provider_status=provider_status,
        retry_eligible=retry_eligible,
        review_opened=review_opened,
        provider_payment_id=provider_payment_id,
    )


def reconcile_funding_unit(
    conn: Connection,
    *,
    funding_unit_id: str,
    actor_context: ActorContext,
    gateway: PaymentGateway | None = None,
) -> ReconciliationResult:
    unit = funding_units_repo.get_by_id(conn, funding_unit_id)
    if unit is None:
        raise ReconciliationError("Funding unit bulunamadı.")
    if gateway is None:
        from backend.app.services.payments.funding_coordinator import make_payment_gateway

        gateway = make_payment_gateway(Settings.from_env(), conn)

    job = processing_jobs.ensure_job(
        conn,
        kind="reconcile",
        source_id=funding_unit_id,
        transaction_id=unit["transaction_id"],
        idempotency_key=f"reconcile:funding-unit:{funding_unit_id}",
    )
    processing_jobs.start_attempt(conn, job["id"], allow_succeeded=True)
    local_payment = provider_payments_repo.get_by_funding_unit(conn, funding_unit_id)
    detail = _safe_provider_detail(gateway, unit)

    if detail is None or detail.outcome is ProviderOperationOutcome.UNKNOWN:
        processing_jobs.mark_unknown(conn, job["id"], reason_code="PROVIDER_DETAIL_UNKNOWN")
        review_opened = _open_ambiguous_review(
            conn, unit=unit, actor_context=actor_context
        )
        return _result(
            conn,
            unit_id=funding_unit_id,
            outcome="ambiguous",
            provider_status=None,
            review_opened=review_opened,
        )

    if detail.outcome is not ProviderOperationOutcome.SUCCESS or detail.payment is None:
        if detail.provider_code in _NOT_FOUND_CODES:
            if unit["status"] == "pool_creation_unknown":
                funding_units_repo.update_status(conn, funding_unit_id, "planned")
                processing_jobs.mark_succeeded(conn, job["id"])
                return _result(
                    conn,
                    unit_id=funding_unit_id,
                    outcome="retry_eligible",
                    provider_status=None,
                    retry_eligible=True,
                )
            if unit["status"] in {"approval_unknown", "pool_created"}:
                funding_units_repo.update_status(conn, funding_unit_id, "pool_created")
                if local_payment is not None:
                    provider_payments_repo.upsert_payment(
                        conn,
                        payment_id=local_payment["id"],
                        funding_unit_id=funding_unit_id,
                        provider_profile=local_payment["provider_profile"],
                        other_trx_code=local_payment["other_trx_code"],
                        virtual_pos_order_id=local_payment["virtual_pos_order_id"],
                        amount_minor=local_payment["amount_minor"],
                        currency=local_payment["currency"],
                        internal_status="pool_waiting",
                    )
                processing_jobs.mark_succeeded(conn, job["id"])
                return _result(
                    conn,
                    unit_id=funding_unit_id,
                    outcome="retry_eligible",
                    provider_status=None,
                    retry_eligible=True,
                )

        processing_jobs.mark_unknown(conn, job["id"], reason_code="PAYMENT_RECONCILE_AMBIGUOUS")
        review_opened = _open_ambiguous_review(
            conn, unit=unit, actor_context=actor_context
        )
        return _result(
            conn,
            unit_id=funding_unit_id,
            outcome="ambiguous",
            provider_status=None,
            review_opened=review_opened,
        )

    provider_payment = detail.payment
    provider_status = provider_payment.status.value
    if not _identifier_matches(unit, provider_payment, local_payment):
        processing_jobs.mark_unknown(conn, job["id"], reason_code="PAYMENT_RECONCILE_AMBIGUOUS")
        review_opened = _open_ambiguous_review(
            conn, unit=unit, actor_context=actor_context
        )
        return _result(
            conn,
            unit_id=funding_unit_id,
            outcome="ambiguous",
            provider_status=provider_status,
            review_opened=review_opened,
        )

    if provider_payment.status is ProviderPaymentStatus.POOL:
        if unit["status"] == "approval_undone" or (
            local_payment is not None
            and local_payment["internal_status"] == "approval_undone"
        ):
            payment = _bind_provider_payment(
                conn,
                unit=unit,
                provider_payment=provider_payment,
                internal_status="pool_waiting",
                existing_payment=local_payment,
            )
            processing_jobs.mark_succeeded(conn, job["id"])
            return _result(
                conn,
                unit_id=funding_unit_id,
                outcome="approval_undone",
                provider_status=provider_status,
                provider_payment_id=payment["id"],
            )
        if unit["status"] in {"approved", "refunded"} or (
            local_payment is not None and local_payment["internal_status"] in {"approved", "refunded"}
        ):
            processing_jobs.mark_unknown(conn, job["id"], reason_code="PAYMENT_RECONCILE_AMBIGUOUS")
            review_opened = _open_ambiguous_review(
                conn, unit=unit, actor_context=actor_context
            )
            return _result(
                conn,
                unit_id=funding_unit_id,
                outcome="ambiguous",
                provider_status=provider_status,
                review_opened=review_opened,
            )
        payment = _bind_provider_payment(
            conn,
            unit=unit,
            provider_payment=provider_payment,
            internal_status="pool_waiting",
            existing_payment=local_payment,
        )
        funding_units_repo.update_status(conn, funding_unit_id, "pool_created")
        instruction = release_instructions_repo.get_by_unit_and_operation(
            conn, funding_unit_id=funding_unit_id, operation_type=_APPROVE_OPERATION
        )
        if instruction is not None and instruction["status"] != "confirmed":
            release_instructions_repo.update_status(conn, instruction["id"], "unknown")
        processing_jobs.mark_succeeded(conn, job["id"])
        return _result(
            conn,
            unit_id=funding_unit_id,
            outcome="pool_created",
            provider_status=provider_status,
            retry_eligible=True,
            provider_payment_id=payment["id"],
        )

    if provider_payment.status is ProviderPaymentStatus.REFUNDED:
        payment = _bind_provider_payment(
            conn,
            unit=unit,
            provider_payment=provider_payment,
            internal_status="refunded",
            existing_payment=local_payment,
        )
        funding_units_repo.update_status(conn, funding_unit_id, "refunded")
        instruction = release_instructions_repo.get_by_unit_and_operation(
            conn, funding_unit_id=funding_unit_id, operation_type="refund"
        )
        if instruction is not None and instruction["status"] != "confirmed":
            release_instructions_repo.update_status(conn, instruction["id"], "confirmed")
        _recompute_aggregates(conn, unit["transaction_id"])
        processing_jobs.mark_succeeded(conn, job["id"])
        return _result(
            conn,
            unit_id=funding_unit_id,
            outcome="refunded",
            provider_status=provider_status,
            provider_payment_id=payment["id"],
        )

    if unit["status"] in {"refunded", "cancelled"}:
        processing_jobs.mark_unknown(conn, job["id"], reason_code="PAYMENT_RECONCILE_AMBIGUOUS")
        review_opened = _open_ambiguous_review(
            conn, unit=unit, actor_context=actor_context
        )
        return _result(
            conn,
            unit_id=funding_unit_id,
            outcome="ambiguous",
            provider_status=provider_status,
            review_opened=review_opened,
        )

    payment = _bind_provider_payment(
        conn,
        unit=unit,
        provider_payment=provider_payment,
        internal_status="approved",
        existing_payment=local_payment,
    )
    instruction = _ensure_approve_instruction(conn, unit=unit, payment=payment)
    release_instructions_repo.update_status(conn, instruction["id"], "confirmed")
    funding_units_repo.update_status(conn, funding_unit_id, "approved")
    _recompute_aggregates(conn, unit["transaction_id"])
    _settle_if_complete(conn, transaction_id=unit["transaction_id"], actor_context=actor_context)
    processing_jobs.mark_succeeded(conn, job["id"])
    emit(
        conn,
        unit["transaction_id"],
        "payment_reconciled",
        {"funding_unit_id": funding_unit_id, "provider_status": provider_status},
        "payment_reconciliation",
    )
    return _result(
        conn,
        unit_id=funding_unit_id,
        outcome="approved",
        provider_status=provider_status,
        provider_payment_id=payment["id"],
    )
