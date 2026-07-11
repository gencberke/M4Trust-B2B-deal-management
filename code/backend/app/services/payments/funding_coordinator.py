"""FundingCoordinator v1/v2.

Plan 04'ün frozen ``ensure_pool_funded`` imzası korunur. 015-017 tabloları
uygulandığında coordinator package schedule'ını funding unit'lere bağlar ve
provider gateway üzerinden her unit için ayrı pool payment oluşturur. Erken
başlangıç branch'inde migration registry henüz değişmediği için, tablolar
yoksa eski Plan 04 provider'sız davranışa güvenli biçimde düşer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from sqlite3 import Connection
from typing import Any
from uuid import uuid4

from backend.app.config import Settings
from backend.app.eventbus import emit
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.repositories import milestones as milestones_repo
from backend.app.repositories import provider_payments as provider_payments_repo
from backend.app.services import audit
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from backend.app.services.account_lifecycle import (
    AccountLifecycleError,
    transition_account_state,
)
from backend.app.services.payments.domain import (
    CreatePoolPaymentCommand,
    PaymentDetailQuery,
    ProviderOperationOutcome,
    ProviderPaymentIdentifier,
    ProviderPaymentStatus,
)
from backend.app.services.payments.ports import FakePaymentGateway, PaymentGateway
from backend.app.services.ratification_package import (
    PackageIntegrityError,
    RatificationPackageError,
    get_current,
    verify_integrity,
)


class FundingCoordinatorError(RatificationPackageError):
    """Funding readiness/coordinator domain hatası."""


@dataclass(frozen=True, slots=True)
class FundingResult:
    transaction_id: str
    package_id: str
    status: str
    event_emitted: bool


def _actor_for_audit(actor: ActorContext) -> audit.AuditActor:
    return audit.AuditActor(
        actor_type="user" if actor.user_id else "system",
        user_id=actor.user_id,
        acting_entity_id=actor.acting_entity_id,
        request_id=actor.request_id,
    )


def _schedule_summary(package) -> tuple[int, int]:
    payload = json.loads(package.canonical_payload_json)
    schedule = payload.get("funding_schedule") or {}
    milestones = schedule.get("milestones") or []
    unit_count = sum(len(milestone.get("funding_units") or []) for milestone in milestones)
    return unit_count, int(schedule.get("total_amount_minor") or 0)


def _has_v2_persistence(conn: Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'funding_units'"
    ).fetchone()
    return row is not None


def _tx8(transaction_id: str) -> str:
    return transaction_id.replace("-", "")[:8]


def _provider_profile(package_payload: dict[str, Any]) -> str:
    return str(package_payload.get("provider_profile") or "moka_standard_v1")


def _persist_package_schedule(conn: Connection, *, transaction_id: str, package) -> list:
    payload = json.loads(package.canonical_payload_json)
    schedule = payload.get("funding_schedule") or {}
    milestones = schedule.get("milestones") or []
    provider_profile = _provider_profile(payload)
    existing = milestones_repo.list_for_package(conn, package.id)
    if existing:
        units = funding_units_repo.list_for_transaction(conn, transaction_id)
        if len(units) == sum(len(item.get("funding_units") or []) for item in milestones):
            return units

    unit_sequence = 0
    for milestone_payload in milestones:
        rule_index = int(milestone_payload["rule_index"])
        milestone = next(
            (row for row in existing if row["rule_index"] == rule_index), None
        )
        if milestone is None:
            milestone = milestones_repo.insert(
                conn,
                milestone_id=milestones_repo.new_id(),
                transaction_id=transaction_id,
                ratification_package_id=package.id,
                rule_set_version_id=payload["rule_set"]["id"],
                rule_index=rule_index,
                title=str(milestone_payload["title"]),
                trigger_type=str(milestone_payload["trigger_type"]),
                percentage_basis_points=int(milestone_payload["basis_points"]),
                amount_minor=int(milestone_payload["amount_minor"]),
                currency=str(milestone_payload["currency"]),
                required_evidence_json=json.dumps(
                    milestone_payload.get("required_evidence") or [],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                release_mode=str(milestone_payload["release_mode"]),
            )

        for unit_payload in milestone_payload.get("funding_units") or []:
            unit_sequence += 1
            existing_unit = funding_units_repo.get_by_package_and_sequence(
                conn, package_id=package.id, sequence=unit_sequence
            )
            if existing_unit is not None:
                continue
            sequence = int(unit_payload["sequence"])
            other_trx_code = f"M4T-{_tx8(transaction_id)}-P{package.version}-U{sequence:02d}"
            funding_units_repo.insert(
                conn,
                unit_id=uuid4().hex,
                transaction_id=transaction_id,
                ratification_package_id=package.id,
                milestone_id=milestone["id"],
                sequence=sequence,
                title=str(milestone_payload["title"]),
                amount_minor=int(unit_payload["amount_minor"]),
                currency=str(milestone_payload["currency"]),
                eligibility_type=str(unit_payload["eligibility_type"]),
                eligibility_payload_json=json.dumps(
                    unit_payload.get("eligibility_payload") or {},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                provider_profile=provider_profile,
                other_trx_code=other_trx_code,
            )
    return funding_units_repo.list_for_transaction(conn, transaction_id)


def persist_funding_schedule(conn: Connection, transaction_id: str, package_id: str) -> list:
    """Idempotently materialize a complete package schedule into 015/016."""

    package = get_current(conn, transaction_id)
    if package is None or package.id != package_id:
        raise FundingCoordinatorError("Package current/latest değil.")
    return _persist_package_schedule(conn, transaction_id=transaction_id, package=package)


def _record_provider_operation(
    conn: Connection,
    *,
    unit,
    provider_payment,
    command: CreatePoolPaymentCommand,
    result,
    attempt_no: int,
) -> None:
    request_payload = {
        "amount_minor": command.amount_minor,
        "currency": command.currency,
        "other_trx_code": command.other_trx_code,
        "is_pool_payment": True,
    }
    request_json = json.dumps(request_payload, sort_keys=True, separators=(",", ":"))
    response_payload = {
        "outcome": result.outcome.value,
        "provider_code": result.provider_code,
    }
    if result.payment is not None:
        response_payload["virtual_pos_order_id"] = result.payment.identifier.virtual_pos_order_id
    response_json = json.dumps(response_payload, sort_keys=True, separators=(",", ":"))
    provider_payments_repo.insert_operation(
        conn,
        funding_unit_id=unit["id"],
        provider_payment_id=provider_payment["id"] if provider_payment else None,
        operation_type="create_pool_payment",
        endpoint="create_pool_payment",
        idempotency_key=f"funding-unit:{unit['id']}:create_pool_payment",
        request_fingerprint=hashlib.sha256(request_json.encode("utf-8")).hexdigest(),
        redacted_request_json=request_json,
        response_json=response_json,
        result_code=result.provider_code,
        is_successful=(result.outcome is ProviderOperationOutcome.SUCCESS),
        outcome=result.outcome.value,
        attempt_no=attempt_no,
    )


def _safe_provider_result(result, *, code: str | None = None):
    """Keep adapter exceptions inside the funding state machine as unknown."""

    if result is not None:
        return result
    from backend.app.services.payments.domain import CreatePoolPaymentResult

    return CreatePoolPaymentResult(
        outcome=ProviderOperationOutcome.UNKNOWN,
        provider_code=code or "PROVIDER_EXCEPTION",
        message="Provider create sonucu belirsiz; reconciliation gerekir.",
    )


def _reconcile_unknown_unit(conn: Connection, *, unit, gateway: PaymentGateway):
    detail = gateway.get_payment_detail(
        query=PaymentDetailQuery(
            identifier=ProviderPaymentIdentifier(other_trx_code=unit["other_trx_code"])
        )
    )
    if detail.outcome is not ProviderOperationOutcome.SUCCESS or detail.payment is None:
        if detail.provider_code == "PROVIDER_PAYMENT_NOT_FOUND":
            funding_units_repo.update_status(conn, unit["id"], "planned")
            return "retry"
        funding_units_repo.update_status(conn, unit["id"], "pool_creation_unknown")
        return "unknown"

    payment = detail.payment
    if payment.status is ProviderPaymentStatus.POOL:
        provider_payments_repo.upsert_payment(
            conn,
            payment_id=uuid4().hex,
            funding_unit_id=unit["id"],
            provider_profile=unit["provider_profile"],
            other_trx_code=unit["other_trx_code"],
            virtual_pos_order_id=payment.identifier.virtual_pos_order_id,
            amount_minor=unit["amount_minor"],
            currency=unit["currency"],
            internal_status="pool_waiting",
        )
        funding_units_repo.update_status(conn, unit["id"], "pool_created")
        return "pool_created"
    funding_units_repo.update_status(conn, unit["id"], "approved")
    return "approved"


def _create_unit_pool_payment(conn: Connection, *, unit, gateway: PaymentGateway) -> str:
    if unit["status"] == "pool_created":
        return "pool_created"
    if unit["status"] == "pool_creation_unknown":
        reconciliation = _reconcile_unknown_unit(conn, unit=unit, gateway=gateway)
        if reconciliation != "retry":
            return reconciliation

    funding_units_repo.update_status(conn, unit["id"], "pool_creation_pending")
    command = CreatePoolPaymentCommand(
        amount_minor=unit["amount_minor"],
        currency=unit["currency"],
        other_trx_code=unit["other_trx_code"],
        description=f"M4Trust funding unit {unit['sequence']:02d}",
    )
    existing_payment = provider_payments_repo.get_by_funding_unit(conn, unit["id"])
    try:
        result = gateway.create_pool_payment(command)
    except Exception:
        result = _safe_provider_result(None)

    if result.payment is not None:
        provider_payment = provider_payments_repo.upsert_payment(
            conn,
            payment_id=existing_payment["id"] if existing_payment else uuid4().hex,
            funding_unit_id=unit["id"],
            provider_profile=unit["provider_profile"],
            other_trx_code=unit["other_trx_code"],
            virtual_pos_order_id=result.payment.identifier.virtual_pos_order_id,
            amount_minor=unit["amount_minor"],
            currency=unit["currency"],
            internal_status=(
                "pool_waiting"
                if result.payment.status is ProviderPaymentStatus.POOL
                else "approved"
            ),
            last_result_code=result.provider_code,
            last_result_message=result.message,
        )
    else:
        provider_payment = existing_payment
        if provider_payment is not None:
            provider_payments_repo.upsert_payment(
                conn,
                payment_id=provider_payment["id"],
                funding_unit_id=unit["id"],
                provider_profile=unit["provider_profile"],
                other_trx_code=unit["other_trx_code"],
                virtual_pos_order_id=None,
                amount_minor=unit["amount_minor"],
                currency=unit["currency"],
                internal_status=(
                    "unknown"
                    if result.outcome is ProviderOperationOutcome.UNKNOWN
                    else "failed"
                ),
                last_result_code=result.provider_code,
                last_result_message=result.message,
            )

    _record_provider_operation(
        conn,
        unit=unit,
        provider_payment=provider_payment,
        command=command,
        result=result,
        attempt_no=funding_units_repo.next_attempt_no(
            conn, funding_unit_id=unit["id"], operation_type="create_pool_payment"
        ),
    )

    if result.outcome is ProviderOperationOutcome.SUCCESS and result.payment is not None:
        funding_units_repo.update_status(conn, unit["id"], "pool_created")
        return "pool_created"
    if result.outcome is ProviderOperationOutcome.UNKNOWN:
        funding_units_repo.update_status(conn, unit["id"], "pool_creation_unknown")
        return "pool_creation_unknown"
    funding_units_repo.update_status(conn, unit["id"], "pool_creation_failed")
    return "pool_creation_failed"


def make_payment_gateway(settings, conn: Connection | None = None) -> PaymentGateway:
    """Select fake SQLite gateway or the existing Moka HTTP adapter."""

    if settings.payment_provider in {"fake", "mock"}:
        if conn is None:
            raise FundingCoordinatorError("Fake gateway için request connection gereklidir.")
        from backend.app.repositories.provider_payments import SQLitePaymentStore

        return FakePaymentGateway(SQLitePaymentStore(conn))
    if settings.payment_provider == "moka_http":
        from backend.app.services.payments.moka.client import MokaPaymentDealerClient

        return MokaPaymentDealerClient.from_settings(settings)
    raise FundingCoordinatorError(
        f"Desteklenmeyen PAYMENT_PROVIDER: {settings.payment_provider!r}"
    )


def _ensure_v1_funding(
    conn: Connection,
    transaction_id: str,
    package_id: str,
    actor_context: ActorContext,
) -> FundingResult:
    tx = conn.execute(
        "SELECT lifecycle_version, state FROM transactions WHERE id = ?",
        (transaction_id,),
    ).fetchone()
    if tx is None:
        raise FundingCoordinatorError("Transaction bulunamadı.")
    if tx["lifecycle_version"] != "account_v2":
        raise FundingCoordinatorError("Legacy transaction funding coordinator'a giremez.")
    package = get_current(conn, transaction_id)
    if package is None or package.id != package_id:
        raise FundingCoordinatorError("Package current/latest değil.")
    if package.status.value != "complete":
        raise FundingCoordinatorError("Package complete olmadan funding_pending üretilemez.")
    if not verify_integrity(package):
        raise PackageIntegrityError("Package canonical hash doğrulaması başarısız.")
    if review_service.has_blocking_case(conn, transaction_id, phase="pre_ratification"):
        raise FundingCoordinatorError("Blocking review case funding'i engelliyor.")

    if tx["state"] == "funding_pending":
        return FundingResult(transaction_id, package_id, "funding_pending", False)
    if tx["state"] in {"active", "settled", "cancelled", "rejected"}:
        raise FundingCoordinatorError("Transaction funding sonrası veya terminal durumda.")

    try:
        transition_account_state(
            conn,
            transaction_id=transaction_id,
            expected_states={"preparation", "awaiting_ratification", "awaiting_approval"},
            target_state="funding_pending",
            actor_context=actor_context,
            reason_code="RATIFICATION_COMPLETE",
        )
    except AccountLifecycleError as exc:
        raise FundingCoordinatorError(str(exc)) from exc

    unit_count, total_amount_minor = _schedule_summary(package)
    emit(
        conn,
        transaction_id,
        "funding_required",
        {
            "package_id": package_id,
            "funding_schedule_version": "funding_schedule_v1",
            "funding_unit_count": unit_count,
            "total_amount_minor": total_amount_minor,
        },
        "funding_coordinator",
    )
    audit.record(
        conn,
        _actor_for_audit(actor_context),
        action="funding.required",
        target=f"ratification_package:{package_id}",
        metadata_allowlist=frozenset({"package_id", "funding_unit_count"}),
        metadata={"package_id": package_id, "funding_unit_count": unit_count},
        transaction_id=transaction_id,
    )
    return FundingResult(transaction_id, package_id, "funding_pending", True)


def ensure_pool_funded(
    conn: Connection,
    transaction_id: str,
    package_id: str,
    actor_context: ActorContext,
) -> FundingResult:
    """Materialize/fund every unit; fallback to frozen v1 until 6A migrations wire."""

    if not _has_v2_persistence(conn):
        return _ensure_v1_funding(conn, transaction_id, package_id, actor_context)

    tx = conn.execute(
        "SELECT lifecycle_version, state FROM transactions WHERE id = ?",
        (transaction_id,),
    ).fetchone()
    if tx is None:
        raise FundingCoordinatorError("Transaction bulunamadı.")
    if tx["lifecycle_version"] != "account_v2":
        raise FundingCoordinatorError("Legacy transaction funding coordinator'a giremez.")
    package = get_current(conn, transaction_id)
    if package is None or package.id != package_id:
        raise FundingCoordinatorError("Package current/latest değil.")
    if package.status.value != "complete":
        raise FundingCoordinatorError("Package complete olmadan funding pending üretilemez.")
    if not verify_integrity(package):
        raise PackageIntegrityError("Package canonical hash doğrulaması başarısız.")
    if review_service.has_blocking_case(conn, transaction_id, phase="pre_ratification"):
        raise FundingCoordinatorError("Blocking review case funding'i engelliyor.")
    existing_units = funding_units_repo.list_for_transaction(conn, transaction_id)
    if tx["state"] == "active" and existing_units and all(
        unit["status"] == "pool_created" for unit in existing_units
    ):
        return FundingResult(transaction_id, package_id, "active", False)
    if tx["state"] in {"active", "settled", "cancelled", "rejected"}:
        raise FundingCoordinatorError("Transaction funding sonrası veya terminal durumda.")

    units = _persist_package_schedule(conn, transaction_id=transaction_id, package=package)
    if not units:
        raise FundingCoordinatorError("Package funding schedule boş olamaz.")
    gateway = make_payment_gateway(Settings.from_env(), conn)
    statuses = [_create_unit_pool_payment(conn, unit=unit, gateway=gateway) for unit in units]
    failed = any(status in {"pool_creation_failed", "pool_creation_unknown", "unknown"} for status in statuses)
    if failed:
        if any(status == "pool_creation_failed" for status in statuses):
            review_service.open_case(
                conn,
                transaction_id=transaction_id,
                phase="payment",
                source_type="payment",
                source_id=package_id,
                reason_code="PAYMENT_POOL_CREATION_FAILED",
                title="Funding unit pool oluşturma başarısız",
                description="Bir veya daha fazla funding unit provider pool durumuna ulaşamadı.",
                severity="blocking",
                actor_context=actor_context,
            )
        return FundingResult(transaction_id, package_id, "funding_pending", False)

    try:
        transition_account_state(
            conn,
            transaction_id=transaction_id,
            expected_states={"funding_pending", "preparation", "awaiting_ratification", "awaiting_approval"},
            target_state="active",
            actor_context=actor_context,
            reason_code="FUNDING_UNITS_POOL_CREATED",
        )
    except AccountLifecycleError as exc:
        raise FundingCoordinatorError(str(exc)) from exc

    emit(
        conn,
        transaction_id,
        "funding_units_pool_created",
        {"package_id": package_id, "funding_unit_count": len(units)},
        "funding_coordinator",
    )
    audit.record(
        conn,
        _actor_for_audit(actor_context),
        action="funding.pool_created",
        target=f"ratification_package:{package_id}",
        metadata_allowlist=frozenset({"package_id", "funding_unit_count"}),
        metadata={"package_id": package_id, "funding_unit_count": len(units)},
        transaction_id=transaction_id,
    )
    return FundingResult(transaction_id, package_id, "active", True)
