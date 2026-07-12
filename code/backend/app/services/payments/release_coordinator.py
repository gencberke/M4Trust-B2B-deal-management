"""ReleaseCoordinator — Faz 6C (Program 06, v2 §8.9, Moka §11/§17).

Eligible funding unit'leri tek tek release eder: her unit için idempotent
release instruction (DB unique) → submit → ``approve_pool_payment(identifier)``
(amount/capture_ratio YOK) → provider detail reconcile → instruction confirmed →
funding unit ``approved`` → milestone aggregate yeniden hesap. Tüm milestone'lar
``released`` olunca transaction ``active`` → ``settled`` (yalnız account lifecycle
servisi üzerinden).

Kurallar (six.md WP2 §3-§5): duplicate evaluation ikinci instruction/approve
üretmez; ``PaymentAlreadyApproved`` otomatik failure değildir (detail gerçekten
approved gösteriyorsa success-equivalent); approve timeout → ``approval_unknown``,
kör retry yok, detail reconciliation; definitive failure ile unknown ayrılır;
provider response ham biçimde persist edilmez; coordinator commit ETMEZ; router
provider çağırmaz.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from sqlite3 import Connection

from backend.app.eventbus import emit
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.repositories import milestones as milestones_repo
from backend.app.repositories import provider_payments as provider_payments_repo
from backend.app.repositories import release_instructions as release_instructions_repo
from backend.app.services import audit
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


class ReleaseCoordinatorError(Exception):
    """Release orchestration domain hatası."""


@dataclass(frozen=True, slots=True)
class ReleaseResult:
    transaction_id: str
    approved_unit_ids: tuple[str, ...]
    unknown_unit_ids: tuple[str, ...]
    failed_unit_ids: tuple[str, ...]
    settled: bool


def _actor_for_audit(actor: ActorContext) -> audit.AuditActor:
    return audit.AuditActor(
        actor_type="user" if actor.user_id else "system",
        user_id=actor.user_id,
        acting_entity_id=actor.acting_entity_id,
        request_id=actor.request_id,
    )


def _record_approve_operation(
    conn: Connection, *, unit, provider_payment, result, outcome: str, attempt_no: int
) -> None:
    request_payload = {
        "operation": _APPROVE_OPERATION,
        "other_trx_code": unit["other_trx_code"],
    }
    request_json = json.dumps(request_payload, sort_keys=True, separators=(",", ":"))
    response_payload = {
        "outcome": outcome,
        "provider_code": getattr(result, "provider_code", None) if result else "PROVIDER_EXCEPTION",
    }
    response_json = json.dumps(response_payload, sort_keys=True, separators=(",", ":"))
    provider_payments_repo.insert_operation(
        conn,
        funding_unit_id=unit["id"],
        provider_payment_id=provider_payment["id"] if provider_payment else None,
        operation_type=_APPROVE_OPERATION,
        endpoint=_APPROVE_OPERATION,
        idempotency_key=f"funding-unit:{unit['id']}:{_APPROVE_OPERATION}",
        request_fingerprint=hashlib.sha256(request_json.encode("utf-8")).hexdigest(),
        redacted_request_json=request_json,
        response_json=response_json,
        result_code=getattr(result, "provider_code", None) if result else "PROVIDER_EXCEPTION",
        is_successful=(outcome == "approved"),
        outcome="success" if outcome == "approved" else ("unknown" if outcome == "unknown" else "failed"),
        attempt_no=attempt_no,
    )


def _mark_unit_approved(conn: Connection, *, unit, provider_payment, instruction) -> None:
    release_instructions_repo.update_status(conn, instruction["id"], "confirmed")
    provider_payments_repo.upsert_payment(
        conn,
        payment_id=provider_payment["id"],
        funding_unit_id=unit["id"],
        provider_profile=provider_payment["provider_profile"],
        other_trx_code=provider_payment["other_trx_code"],
        virtual_pos_order_id=provider_payment["virtual_pos_order_id"],
        amount_minor=provider_payment["amount_minor"],
        currency=provider_payment["currency"],
        internal_status="approved",
    )
    funding_units_repo.update_status(conn, unit["id"], "approved")


def _detail_shows_approved(gateway: PaymentGateway, *, unit) -> bool:
    detail = gateway.get_payment_detail(
        query=PaymentDetailQuery(
            identifier=ProviderPaymentIdentifier(other_trx_code=unit["other_trx_code"])
        )
    )
    return (
        detail.outcome is ProviderOperationOutcome.SUCCESS
        and detail.payment is not None
        and detail.payment.status is ProviderPaymentStatus.APPROVED
    )


def _reconcile_unknown_approval(
    conn: Connection, *, unit, provider_payment, instruction, gateway: PaymentGateway
) -> str:
    """approval_unknown unit'i provider detail ile mutabık kılar (kör approve yok).

    approved → confirmed (success-equivalent) · hâlâ pool → kontrollü retry ('retry')
    · not-found/error → belirsiz kalır ('unknown'), manuel kurtarma; approve YENİDEN
    çağrılmaz.
    """

    detail = gateway.get_payment_detail(
        query=PaymentDetailQuery(
            identifier=ProviderPaymentIdentifier(other_trx_code=unit["other_trx_code"])
        )
    )
    if detail.outcome is ProviderOperationOutcome.SUCCESS and detail.payment is not None:
        if detail.payment.status is ProviderPaymentStatus.APPROVED:
            _mark_unit_approved(
                conn, unit=unit, provider_payment=provider_payment, instruction=instruction
            )
            return "approved"
        return "retry"
    return "unknown"


def _release_one_unit(conn: Connection, *, unit_id: str, gateway: PaymentGateway) -> str:
    unit = funding_units_repo.get_by_id(conn, unit_id)
    if unit is None:
        raise ReleaseCoordinatorError(f"Funding unit bulunamadı: {unit_id}")
    if unit["status"] == "approved":
        return "already"

    provider_payment = provider_payments_repo.get_by_funding_unit(conn, unit_id)
    if provider_payment is None or provider_payment["virtual_pos_order_id"] is None:
        # Guard: pool_created olmadan approve edilemez (release guard'ın parçası).
        raise ReleaseCoordinatorError(
            f"Funding unit {unit_id} approve öncesi pool payment sahibi olmalı."
        )

    instruction = release_instructions_repo.get_by_unit_and_operation(
        conn, funding_unit_id=unit_id, operation_type=_APPROVE_OPERATION
    )
    if instruction is None:
        instruction = release_instructions_repo.insert(
            conn,
            funding_unit_id=unit_id,
            provider_payment_id=provider_payment["id"],
            idempotency_key=f"funding-unit:{unit_id}:{_APPROVE_OPERATION}",
            amount_minor=unit["amount_minor"],
            currency=unit["currency"],
            provider=unit["provider_profile"],
            provider_reference=provider_payment["virtual_pos_order_id"],
        )
    if instruction["status"] == "confirmed":
        # Duplicate evaluation: ikinci approve çağrısı yok, idempotent tamamla.
        _mark_unit_approved(conn, unit=unit, provider_payment=provider_payment, instruction=instruction)
        return "already"

    # approval_unknown (approve timeout): önce reconcile, kör re-approve YOK.
    if unit["status"] == "approval_unknown":
        reconciled = _reconcile_unknown_approval(
            conn, unit=unit, provider_payment=provider_payment,
            instruction=instruction, gateway=gateway,
        )
        if reconciled != "retry":
            return reconciled
        # detail hâlâ pool: kontrollü retry -- approve tekrar denenebilir.

    identifier = ProviderPaymentIdentifier(
        virtual_pos_order_id=provider_payment["virtual_pos_order_id"],
        other_trx_code=unit["other_trx_code"],
    )
    release_instructions_repo.update_status(conn, instruction["id"], "submitted")
    funding_units_repo.update_status(conn, unit_id, "approval_pending")

    try:
        result = gateway.approve_pool_payment(identifier)
    except Exception:
        result = None

    attempt_no = funding_units_repo.next_attempt_no(
        conn, funding_unit_id=unit_id, operation_type=_APPROVE_OPERATION
    )

    success = result is not None and result.outcome is ProviderOperationOutcome.SUCCESS
    already_approved = (
        result is not None
        and result.outcome is ProviderOperationOutcome.FAILED
        and result.provider_code == "PAYMENT_ALREADY_APPROVED"
    )
    # PaymentAlreadyApproved otomatik failure DEĞİL: detail gerçekten approved
    # gösteriyorsa success-equivalent (Moka §11.5).
    if already_approved and _detail_shows_approved(gateway, unit=unit):
        success = True
    if success:
        _mark_unit_approved(conn, unit=unit, provider_payment=provider_payment, instruction=instruction)
        _record_approve_operation(
            conn, unit=unit, provider_payment=provider_payment, result=result,
            outcome="approved", attempt_no=attempt_no,
        )
        return "approved"

    unknown = result is None or result.outcome is ProviderOperationOutcome.UNKNOWN
    if unknown:
        # Timeout/belirsiz: kör retry YOK; detail reconcile approved gösterirse
        # success-equivalent, aksi halde approval_unknown olarak bırak.
        if _detail_shows_approved(gateway, unit=unit):
            _mark_unit_approved(conn, unit=unit, provider_payment=provider_payment, instruction=instruction)
            _record_approve_operation(
                conn, unit=unit, provider_payment=provider_payment, result=result,
                outcome="approved", attempt_no=attempt_no,
            )
            return "approved"
        release_instructions_repo.update_status(conn, instruction["id"], "unknown")
        provider_payments_repo.upsert_payment(
            conn,
            payment_id=provider_payment["id"],
            funding_unit_id=unit_id,
            provider_profile=provider_payment["provider_profile"],
            other_trx_code=provider_payment["other_trx_code"],
            virtual_pos_order_id=provider_payment["virtual_pos_order_id"],
            amount_minor=provider_payment["amount_minor"],
            currency=provider_payment["currency"],
            internal_status="approval_unknown",
        )
        funding_units_repo.update_status(conn, unit_id, "approval_unknown")
        _record_approve_operation(
            conn, unit=unit, provider_payment=provider_payment, result=result,
            outcome="unknown", attempt_no=attempt_no,
        )
        return "unknown"

    # Definitive failure (unknown DEĞİL): instruction failed, unit pool_created'a döner.
    release_instructions_repo.update_status(conn, instruction["id"], "failed")
    funding_units_repo.update_status(conn, unit_id, "pool_created")
    _record_approve_operation(
        conn, unit=unit, provider_payment=provider_payment, result=result,
        outcome="failed", attempt_no=attempt_no,
    )
    return "failed"


def _recompute_milestone_aggregates(conn: Connection, transaction_id: str) -> None:
    for milestone in milestones_repo.list_for_transaction(conn, transaction_id):
        units = funding_units_repo.list_for_milestone(conn, milestone["id"])
        released = sum(
            int(unit["amount_minor"]) for unit in units if unit["status"] == "approved"
        )
        if released <= 0:
            continue
        total = int(milestone["amount_minor"])
        status = "released" if released >= total else "partially_released"
        if milestone["released_amount_minor"] == released and milestone["status"] == status:
            continue
        milestones_repo.update_released_amount(
            conn, milestone["id"], released_amount_minor=released, status=status
        )


def _settle_if_all_released(
    conn: Connection, transaction_id: str, actor_context: ActorContext
) -> bool:
    milestones = milestones_repo.list_for_transaction(conn, transaction_id)
    if not milestones or not all(m["status"] == "released" for m in milestones):
        return False
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
        return False
    if not transitioned:
        return False
    emit(
        conn,
        transaction_id,
        "transaction_settled",
        {"milestone_count": len(milestones)},
        "release_coordinator",
    )
    return True


def release_units(
    conn: Connection,
    *,
    transaction_id: str,
    unit_ids: tuple[str, ...],
    gateway: PaymentGateway,
    actor_context: ActorContext,
) -> ReleaseResult:
    """Eligible funding unit'leri idempotent biçimde release eder ve milestone
    aggregate + settled lifecycle'ını günceller. Çağıran commit sorumluluğunu
    taşır; bu fonksiyon commit ETMEZ."""

    approved: list[str] = []
    unknown: list[str] = []
    failed: list[str] = []
    for unit_id in unit_ids:
        outcome = _release_one_unit(conn, unit_id=unit_id, gateway=gateway)
        if outcome == "approved":
            approved.append(unit_id)
        elif outcome == "unknown":
            unknown.append(unit_id)
        elif outcome == "failed":
            failed.append(unit_id)

    _recompute_milestone_aggregates(conn, transaction_id)
    settled = _settle_if_all_released(conn, transaction_id, actor_context)

    if approved:
        emit(
            conn,
            transaction_id,
            "funding_units_approved",
            {"funding_unit_count": len(approved)},
            "release_coordinator",
        )
        audit.record(
            conn,
            _actor_for_audit(actor_context),
            action="funding.units_approved",
            target=f"transaction:{transaction_id}",
            metadata_allowlist=frozenset({"funding_unit_count"}),
            metadata={"funding_unit_count": len(approved)},
            transaction_id=transaction_id,
        )

    return ReleaseResult(
        transaction_id=transaction_id,
        approved_unit_ids=tuple(approved),
        unknown_unit_ids=tuple(unknown),
        failed_unit_ids=tuple(failed),
        settled=settled,
    )
