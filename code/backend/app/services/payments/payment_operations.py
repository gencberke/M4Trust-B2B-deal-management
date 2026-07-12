"""İnsan kontrollü payment undo/refund ve release retry servisleri.

Router yalnız authorization/orchestration çağrısı yapar; provider adapter
çağrısı bu modülde ve ReleaseCoordinator'da kalır. Exact Moka refund contract'ı
frozen olmadığı için gateway refund capability'si yoksa fail-closed unsupported
sonucu üretilir.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from sqlite3 import Connection, IntegrityError

from backend.app.config import Settings
from backend.app.eventbus import emit
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.repositories import milestones as milestones_repo
from backend.app.repositories import payment_resolutions as resolutions_repo
from backend.app.repositories import participants as participants_repo
from backend.app.repositories import provider_payments as provider_payments_repo
from backend.app.repositories import release_instructions as release_instructions_repo
from backend.app.services import audit
from backend.app.services import processing_jobs
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from backend.app.services.account_lifecycle import transition_account_state
from backend.app.services.payments.domain import (
    ProviderOperationOutcome,
    ProviderPaymentIdentifier,
    ProviderPaymentStatus,
)
from backend.app.services.payments.funding_coordinator import make_payment_gateway
from backend.app.services.payments.ports import (
    PaymentGateway,
)

_PLATFORM_ROLES = frozenset({"reviewer", "admin"})
_SAFE_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class PaymentOperationError(ValueError):
    """Payment operation domain/authorization hatası."""


@dataclass(frozen=True, slots=True)
class PaymentOperationResult:
    resolution_id: str
    funding_unit_id: str
    operation_type: str
    status: str
    provider_outcome: str | None = None
    provider_code: str | None = None


def _now_actor(actor: ActorContext) -> audit.AuditActor:
    return audit.AuditActor(
        actor_type="user" if actor.user_id else "system",
        user_id=actor.user_id,
        acting_entity_id=actor.acting_entity_id,
        request_id=actor.request_id,
    )


def _safe_idempotency(value: str | None, *, fallback: str) -> str:
    if value and _SAFE_IDEMPOTENCY_RE.fullmatch(value):
        return value
    return fallback


def _unit_with_transaction(conn: Connection, funding_unit_id: str):
    return conn.execute(
        """SELECT fu.*, t.lifecycle_version, t.state AS transaction_state
        FROM funding_units fu
        JOIN transactions t ON t.id = fu.transaction_id
        WHERE fu.id = ?""",
        (funding_unit_id,),
    ).fetchone()


def actor_is_transaction_manager(
    conn: Connection, *, transaction_id: str, actor: ActorContext
) -> bool:
    if actor.user_id is None or actor.acting_entity_id is None:
        return False
    row = participants_repo.get_active_assignment(
        conn, transaction_id, actor.user_id, role="manager"
    )
    return row is not None and row["legal_entity_id"] == actor.acting_entity_id


def _participant_role_for_actor(
    conn: Connection, *, transaction_id: str, actor: ActorContext
) -> str | None:
    if actor.user_id is None or actor.acting_entity_id is None:
        return None
    assignments = conn.execute(
        "SELECT participant_id FROM transaction_assignments "
        "WHERE transaction_id = ? AND user_id = ? AND legal_entity_id = ? "
        "AND role = 'approver' AND status = 'active'",
        (transaction_id, actor.user_id, actor.acting_entity_id),
    ).fetchall()
    for assignment in assignments:
        if assignment["participant_id"] is None:
            continue
        participant = conn.execute(
            "SELECT role FROM transaction_participants WHERE id = ?",
            (assignment["participant_id"],),
        ).fetchone()
        if participant is not None and participant["role"] in {"buyer", "seller"}:
            return participant["role"]
    return None


def _open_resolution_case(
    conn: Connection,
    *,
    unit,
    operation_type: str,
    source_id: str,
    actor_context: ActorContext,
    reason_code: str | None = None,
):
    reason = reason_code or (
        "PAYMENT_UNDO_REQUESTED"
        if operation_type == "undo_approval"
        else "PAYMENT_REFUND_REQUESTED"
    )
    title = (
        "Payment approval undo insan onayı bekliyor"
        if operation_type == "undo_approval"
        else "Payment refund insan onayı bekliyor"
    )
    description = (
        "Funding unit için para hareketi tersine çevirme talebi açıldı."
        if operation_type == "undo_approval"
        else "Funding unit için tam refund talebi açıldı."
    )
    return review_service.open_case(
        conn,
        transaction_id=unit["transaction_id"],
        phase="payment",
        source_type="payment",
        source_id=source_id,
        reason_code=reason,
        title=title,
        description=description,
        severity="blocking",
        actor_context=actor_context,
    )


def request_resolution(
    conn: Connection,
    *,
    funding_unit_id: str,
    operation_type: str,
    actor_context: ActorContext,
    idempotency_key: str | None = None,
) -> object:
    if operation_type not in {"undo_approval", "refund"}:
        raise PaymentOperationError("Desteklenmeyen payment resolution türü.")
    if actor_context.user_id is None or actor_context.acting_entity_id is None:
        raise PaymentOperationError("Payment resolution için authenticated actor gerekir.")
    unit = _unit_with_transaction(conn, funding_unit_id)
    if unit is None:
        raise PaymentOperationError("Funding unit bulunamadı.")
    if unit["lifecycle_version"] != "account_v2":
        raise PaymentOperationError("Legacy funding unit reversal'a giremez.")
    if not actor_is_transaction_manager(
        conn, transaction_id=unit["transaction_id"], actor=actor_context
    ):
        raise PaymentOperationError("Yalnız transaction manager reversal talebi açabilir.")

    key = _safe_idempotency(
        idempotency_key,
        fallback=f"resolution:{operation_type}:{funding_unit_id}",
    )
    existing = resolutions_repo.get_by_idempotency(conn, key)
    if existing is None:
        existing = resolutions_repo.get_by_unit_and_operation(
            conn, funding_unit_id=funding_unit_id, operation_type=operation_type
        )
    if existing is not None:
        return existing

    case = _open_resolution_case(
        conn,
        unit=unit,
        operation_type=operation_type,
        source_id=funding_unit_id,
        actor_context=actor_context,
    )
    try:
        resolution = resolutions_repo.insert(
            conn,
            transaction_id=unit["transaction_id"],
            funding_unit_id=funding_unit_id,
            review_case_id=case.id,
            operation_type=operation_type,
            idempotency_key=key,
            requested_by_user_id=actor_context.user_id,
            requested_by_entity_id=actor_context.acting_entity_id,
        )
    except IntegrityError:
        existing = resolutions_repo.get_by_idempotency(conn, key)
        if existing is None:
            raise
        return existing

    emit(
        conn,
        unit["transaction_id"],
        "payment_resolution_requested",
        {"funding_unit_id": funding_unit_id, "operation_type": operation_type},
        "payment_operations",
    )
    audit.record(
        conn,
        _now_actor(actor_context),
        action="payment.resolution_requested",
        target=f"payment_resolution:{resolution['id']}",
        metadata_allowlist=frozenset({"operation_type"}),
        metadata={"operation_type": operation_type},
        transaction_id=unit["transaction_id"],
    )
    return resolution


def approve_resolution(
    conn: Connection,
    *,
    resolution_id: str,
    actor_context: ActorContext,
) -> object:
    resolution = resolutions_repo.get_by_id(conn, resolution_id)
    if resolution is None:
        raise PaymentOperationError("Payment resolution bulunamadı.")
    role = _participant_role_for_actor(
        conn, transaction_id=resolution["transaction_id"], actor=actor_context
    )
    if role is None:
        raise PaymentOperationError("Yalnız buyer/seller participant approver resolution onaylayabilir.")
    if resolution["status"] not in {"requested", "authorized"}:
        raise PaymentOperationError("Resolution artık approval kabul etmiyor.")
    existing = resolutions_repo.get_approval(
        conn, resolution_id=resolution_id, participant_role=role
    )
    if existing is not None:
        return resolution
    try:
        resolutions_repo.insert_approval(
            conn,
            resolution_id=resolution_id,
            participant_role=role,
            user_id=actor_context.user_id or "",
            acting_entity_id=actor_context.acting_entity_id or "",
        )
    except IntegrityError as exc:
        raise PaymentOperationError(
            "Aynı resolution için actor iki tarafı temsil edemez veya role zaten onaylanmıştır."
        ) from exc

    approvals = resolutions_repo.list_approvals(conn, resolution_id)
    status = "authorized" if {row["participant_role"] for row in approvals} == {"buyer", "seller"} else "requested"
    resolution = resolutions_repo.update_status(conn, resolution_id, status=status)
    if status == "authorized":
        emit(
            conn,
            resolution["transaction_id"],
            "payment_resolution_authorized",
            {"resolution_id": resolution_id, "operation_type": resolution["operation_type"]},
            "payment_operations",
        )
    audit.record(
        conn,
        _now_actor(actor_context),
        action="payment.resolution_approved",
        target=f"payment_resolution:{resolution_id}",
        metadata_allowlist=frozenset({"approver_role"}),
        metadata={"approver_role": role},
        transaction_id=resolution["transaction_id"],
    )
    return resolution


def _can_execute(conn: Connection, resolution, actor_context: ActorContext) -> bool:
    if actor_context.platform_role in _PLATFORM_ROLES:
        return True
    approvals = resolutions_repo.list_approvals(conn, resolution["id"])
    return {row["participant_role"] for row in approvals} == {"buyer", "seller"}


def _record_operation(
    conn: Connection,
    *,
    unit,
    provider_payment,
    operation_type: str,
    result,
    attempt_no: int,
) -> None:
    request_payload = {
        "operation": operation_type,
        "other_trx_code": unit["other_trx_code"],
    }
    request_json = json.dumps(request_payload, sort_keys=True, separators=(",", ":"))
    response_json = json.dumps(
        {
            "outcome": result.outcome.value if result is not None else "unknown",
            "provider_code": getattr(result, "provider_code", None) if result else "PROVIDER_EXCEPTION",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    provider_payments_repo.insert_operation(
        conn,
        funding_unit_id=unit["id"],
        provider_payment_id=provider_payment["id"] if provider_payment else None,
        operation_type=operation_type,
        endpoint=operation_type,
        idempotency_key=f"payment-operation:{unit['id']}:{operation_type}",
        request_fingerprint=hashlib.sha256(request_json.encode("utf-8")).hexdigest(),
        redacted_request_json=request_json,
        response_json=response_json,
        result_code=getattr(result, "provider_code", None) if result else "PROVIDER_EXCEPTION",
        is_successful=(
            result is not None and result.outcome is ProviderOperationOutcome.SUCCESS
        ),
        outcome=(
            result.outcome.value
            if result is not None
            else ProviderOperationOutcome.UNKNOWN.value
        ),
        attempt_no=attempt_no,
    )


def _recompute_aggregates(conn: Connection, transaction_id: str) -> None:
    for milestone in milestones_repo.list_for_transaction(conn, transaction_id):
        units = funding_units_repo.list_for_milestone(conn, milestone["id"])
        released = sum(int(u["amount_minor"]) for u in units if u["status"] == "approved")
        total = int(milestone["amount_minor"])
        if units and all(u["status"] in {"refunded", "cancelled"} for u in units):
            status = "cancelled"
        elif released >= total:
            status = "released"
        elif released > 0:
            status = "partially_released"
        else:
            status = "pending"
        if int(milestone["released_amount_minor"]) != released or milestone["status"] != status:
            milestones_repo.update_released_amount(
                conn, milestone["id"], released_amount_minor=released, status=status
            )


def _transition_after_undo(conn: Connection, *, unit, actor_context: ActorContext) -> None:
    if unit["transaction_state"] != "settled":
        return
    try:
        transition_account_state(
            conn,
            transaction_id=unit["transaction_id"],
            expected_states={"settled"},
            target_state="active",
            actor_context=actor_context,
            reason_code="PAYMENT_APPROVAL_UNDONE",
        )
    except Exception:
        return


def _transition_after_refund(conn: Connection, *, unit, actor_context: ActorContext) -> None:
    units = funding_units_repo.list_for_transaction(conn, unit["transaction_id"])
    if units and all(u["status"] in {"refunded", "cancelled"} for u in units):
        target = "cancelled"
    else:
        target = "active"
    tx = conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (unit["transaction_id"],)
    ).fetchone()
    if tx is None or tx["state"] == target:
        return
    try:
        transition_account_state(
            conn,
            transaction_id=unit["transaction_id"],
            expected_states={"active", "settled", "funding_pending"},
            target_state=target,
            actor_context=actor_context,
            reason_code="PAYMENT_REFUNDED",
        )
    except Exception:
        return


def _resolution_instruction(conn: Connection, *, unit, provider_payment, operation_type: str):
    instruction = release_instructions_repo.get_by_unit_and_operation(
        conn, funding_unit_id=unit["id"], operation_type=operation_type
    )
    if instruction is None:
        instruction = release_instructions_repo.insert(
            conn,
            funding_unit_id=unit["id"],
            provider_payment_id=provider_payment["id"],
            idempotency_key=f"payment-operation:{unit['id']}:{operation_type}",
            amount_minor=unit["amount_minor"],
            currency=unit["currency"],
            provider=unit["provider_profile"],
            provider_reference=provider_payment["virtual_pos_order_id"],
            operation_type=operation_type,
        )
    return instruction


def _open_blocked_case(
    conn: Connection,
    *,
    resolution,
    unit,
    actor_context: ActorContext,
    reason_code: str,
) -> None:
    # Yusuf'un 7B frozen kontratı: TEK açılış kapısı `open_payment_review_case`
    # (phase/source_type/severity sabit, source_id=funding_unit_id, reason_code
    # dondurulmuş `PAYMENT_REASON_CODES` kümesiyle fail-closed sınırlı).
    review_service.open_payment_review_case(
        conn,
        transaction_id=unit["transaction_id"],
        funding_unit_id=unit["id"],
        reason_code=reason_code,
        title="Payment reversal provider tarafından engellendi",
        description="Provider reversal işlemi güvenli biçimde tamamlanamadı.",
        actor_context=actor_context,
    )


def execute_resolution(
    conn: Connection,
    *,
    resolution_id: str,
    actor_context: ActorContext,
    gateway: PaymentGateway | None = None,
) -> PaymentOperationResult:
    resolution = resolutions_repo.get_by_id(conn, resolution_id)
    if resolution is None:
        raise PaymentOperationError("Payment resolution bulunamadı.")
    if resolution["status"] == "executed":
        return PaymentOperationResult(
            resolution_id=resolution_id,
            funding_unit_id=resolution["funding_unit_id"],
            operation_type=resolution["operation_type"],
            status="executed",
        )
    if resolution["status"] == "unknown":
        raise PaymentOperationError(
            "Unknown reversal sonucu reconciliation olmadan tekrar yürütülemez."
        )
    if not _can_execute(conn, resolution, actor_context):
        raise PaymentOperationError(
            "Undo/refund yalnız platform reviewer/admin veya bilateral buyer+seller onayıyla yürütülebilir."
        )
    if resolution["status"] not in {"requested", "authorized"}:
        raise PaymentOperationError("Payment resolution yürütülebilir durumda değil.")

    unit = _unit_with_transaction(conn, resolution["funding_unit_id"])
    provider_payment = provider_payments_repo.get_by_funding_unit(
        conn, resolution["funding_unit_id"]
    )
    if unit is None or provider_payment is None:
        raise PaymentOperationError("Funding unit/provider payment bulunamadı.")
    if unit["status"] != "approved" or provider_payment["internal_status"] != "approved":
        raise PaymentOperationError(
            "Undo/refund precondition: funding unit ve provider payment approved olmalıdır."
        )

    operation_type = (
        "undo_pool_approval"
        if resolution["operation_type"] == "undo_approval"
        else "refund"
    )
    job = processing_jobs.ensure_job(
        conn,
        kind="release",
        source_id=resolution_id,
        transaction_id=unit["transaction_id"],
        idempotency_key=f"release:resolution:{resolution_id}",
    )
    processing_jobs.start_attempt(conn, job["id"])
    if gateway is None:
        gateway = make_payment_gateway(Settings.from_env(), conn)
    identifier = ProviderPaymentIdentifier(
        virtual_pos_order_id=provider_payment["virtual_pos_order_id"],
        other_trx_code=provider_payment["other_trx_code"],
    )

    provider_method = (
        gateway.undo_pool_approval
        if resolution["operation_type"] == "undo_approval"
        else getattr(gateway, "refund_payment", None)
    )
    if provider_method is None:
        _open_blocked_case(
            conn,
            resolution=resolution,
            unit=unit,
            actor_context=actor_context,
            reason_code=review_service.PAYMENT_REFUND_FAILED,
        )
        resolutions_repo.update_status(conn, resolution_id, status="failed")
        processing_jobs.mark_failed(conn, job["id"], reason_code="PAYMENT_REFUND_UNSUPPORTED")
        return PaymentOperationResult(
            resolution_id=resolution_id,
            funding_unit_id=unit["id"],
            operation_type=resolution["operation_type"],
            status="failed",
            provider_outcome="unsupported",
            provider_code="PAYMENT_REFUND_UNSUPPORTED",
        )

    provider_exception_code: str | None = None
    provider_exception_message: str = ""
    try:
        result = provider_method(identifier)
    except Exception as exc:
        result = None
        provider_exception_code = getattr(exc, "result_code", None)
        provider_exception_message = str(getattr(exc, "result_message", ""))[:120]
    attempt_no = funding_units_repo.next_attempt_no(
        conn, funding_unit_id=unit["id"], operation_type=operation_type
    )
    _record_operation(
        conn,
        unit=unit,
        provider_payment=provider_payment,
        operation_type=operation_type,
        result=result,
        attempt_no=attempt_no,
    )

    exception_statement_closed = (
        result is None
        and resolution["operation_type"] == "undo_approval"
        and (
            provider_exception_code in {"HTTP_409", "STATEMENT_CLOSED", "PAYMENT_UNDO_BLOCKED"}
            or "statement_closed" in provider_exception_message.lower()
        )
    )
    if exception_statement_closed:
        _open_blocked_case(
            conn,
            resolution=resolution,
            unit=unit,
            actor_context=actor_context,
            reason_code="PAYMENT_UNDO_BLOCKED",
        )
        resolutions_repo.update_status(conn, resolution_id, status="failed")
        processing_jobs.mark_failed(conn, job["id"], reason_code="PAYMENT_UNDO_BLOCKED")
        return PaymentOperationResult(
            resolution_id=resolution_id,
            funding_unit_id=unit["id"],
            operation_type=resolution["operation_type"],
            status="failed",
            provider_outcome="failed",
            provider_code="PAYMENT_UNDO_BLOCKED",
        )
    if result is None or result.outcome is ProviderOperationOutcome.UNKNOWN:
        resolutions_repo.update_status(conn, resolution_id, status="unknown")
        processing_jobs.mark_unknown(conn, job["id"], reason_code="PROVIDER_OPERATION_UNKNOWN")
        return PaymentOperationResult(
            resolution_id=resolution_id,
            funding_unit_id=unit["id"],
            operation_type=resolution["operation_type"],
            status="unknown",
            provider_outcome="unknown",
            provider_code=(
                getattr(result, "provider_code", None)
                if result
                else provider_exception_code or "PROVIDER_EXCEPTION"
            ),
        )
    if result.outcome is ProviderOperationOutcome.FAILED:
        provider_code = result.provider_code or "PAYMENT_OPERATION_FAILED"
        statement_closed = (
            resolution["operation_type"] == "undo_approval"
            and ("STATEMENT_CLOSED" in provider_code or "statement_closed" in (result.message or ""))
        )
        if statement_closed:
            _open_blocked_case(
                conn,
                resolution=resolution,
                unit=unit,
                actor_context=actor_context,
                reason_code="PAYMENT_UNDO_BLOCKED",
            )
        resolutions_repo.update_status(conn, resolution_id, status="failed")
        processing_jobs.mark_failed(conn, job["id"], reason_code=(
            "PAYMENT_UNDO_BLOCKED" if statement_closed else "PAYMENT_OPERATION_FAILED"
        ))
        return PaymentOperationResult(
            resolution_id=resolution_id,
            funding_unit_id=unit["id"],
            operation_type=resolution["operation_type"],
            status="failed",
            provider_outcome="failed",
            provider_code=provider_code,
        )

    instruction = _resolution_instruction(
        conn,
        unit=unit,
        provider_payment=provider_payment,
        operation_type=operation_type,
    )
    release_instructions_repo.update_status(conn, instruction["id"], "confirmed")
    new_internal_status = (
        "approval_undone"
        if resolution["operation_type"] == "undo_approval"
        else "refunded"
    )
    new_unit_status = (
        "approval_undone"
        if resolution["operation_type"] == "undo_approval"
        else "refunded"
    )
    provider_payments_repo.upsert_payment(
        conn,
        payment_id=provider_payment["id"],
        funding_unit_id=unit["id"],
        provider_profile=provider_payment["provider_profile"],
        other_trx_code=provider_payment["other_trx_code"],
        virtual_pos_order_id=provider_payment["virtual_pos_order_id"],
        amount_minor=provider_payment["amount_minor"],
        currency=provider_payment["currency"],
        internal_status=new_internal_status,
    )
    funding_units_repo.update_status(conn, unit["id"], new_unit_status)
    _recompute_aggregates(conn, unit["transaction_id"])
    if resolution["operation_type"] == "undo_approval":
        _transition_after_undo(conn, unit=unit, actor_context=actor_context)
        event_type = "payment_approval_undone"
        action = "payment.approval_undone"
    else:
        _transition_after_refund(conn, unit=unit, actor_context=actor_context)
        event_type = "payment_refunded"
        action = "payment.refunded"
    resolutions_repo.update_status(
        conn,
        resolution_id,
        status="executed",
        executed_by_user_id=actor_context.user_id,
    )
    emit(
        conn,
        unit["transaction_id"],
        event_type,
        {"funding_unit_id": unit["id"], "resolution_id": resolution_id},
        "payment_operations",
    )
    audit.record(
        conn,
        _now_actor(actor_context),
        action=action,
        target=f"payment_resolution:{resolution_id}",
        metadata_allowlist=frozenset({"funding_unit_id", "operation_type"}),
        metadata={
            "funding_unit_id": unit["id"],
            "operation_type": resolution["operation_type"],
        },
        transaction_id=unit["transaction_id"],
    )
    processing_jobs.mark_succeeded(conn, job["id"])
    return PaymentOperationResult(
        resolution_id=resolution_id,
        funding_unit_id=unit["id"],
        operation_type=resolution["operation_type"],
        status="executed",
        provider_outcome="success",
    )


def get_payment_trace(conn: Connection, transaction_id: str) -> list[dict]:
    """Provider operations'tan secret-free, JSON-safe trace projection'ı üretir."""

    operations = provider_payments_repo.list_operations_for_transaction(conn, transaction_id)
    result: list[dict] = []
    for operation in operations:
        try:
            redacted_request = json.loads(operation["redacted_request_json"])
        except (TypeError, ValueError):
            redacted_request = {}
        try:
            redacted_response = (
                json.loads(operation["response_json"])
                if operation["response_json"] is not None
                else None
            )
        except (TypeError, ValueError):
            redacted_response = None
        result.append(
            {
                "operation_type": operation["operation_type"],
                "endpoint": operation["endpoint"],
                "timestamp": operation["created_at"],
                "attempt_no": operation["attempt_no"],
                "outcome": operation["outcome"],
                "OtherTrxCode": operation["other_trx_code"],
                "VirtualPosOrderId": operation["virtual_pos_order_id"],
                "amount_minor": operation["amount_minor"],
                "currency": operation["currency"],
                "idempotency_key": operation["idempotency_key"],
                "request_fingerprint": operation["request_fingerprint"],
                "redacted_request": redacted_request,
                "response": redacted_response,
                "http_status": operation["http_status"],
                "result_code": operation["result_code"],
                "is_successful": (
                    None
                    if operation["is_successful"] is None
                    else bool(operation["is_successful"])
                ),
                "mapped_status": operation["outcome"],
            }
        )
    return result


def retry_release_instruction(
    conn: Connection,
    *,
    instruction_id: str,
    actor_context: ActorContext,
    gateway: PaymentGateway | None = None,
) -> dict:
    """Aynı instruction için yeni provider attempt'i üretir."""

    instruction = conn.execute(
        """SELECT ri.*, fu.transaction_id, fu.id AS unit_id, fu.status AS unit_status,
            t.lifecycle_version
        FROM release_instructions ri
        JOIN funding_units fu ON fu.id = ri.funding_unit_id
        JOIN transactions t ON t.id = fu.transaction_id
        WHERE ri.id = ?""",
        (instruction_id,),
    ).fetchone()
    if instruction is None:
        raise PaymentOperationError("Release instruction bulunamadı.")
    if instruction["status"] not in {"failed", "unknown"}:
        raise PaymentOperationError("Yalnız failed veya unknown instruction retry edilebilir.")
    if instruction["lifecycle_version"] != "account_v2":
        raise PaymentOperationError("Legacy release instruction retry kapsamı dışındadır.")
    if not (
        actor_context.platform_role in _PLATFORM_ROLES
        or actor_is_transaction_manager(
            conn, transaction_id=instruction["transaction_id"], actor=actor_context
        )
    ):
        raise PaymentOperationError("Release retry için transaction manager veya platform reviewer gerekir.")

    if gateway is None:
        gateway = make_payment_gateway(Settings.from_env(), conn)

    from backend.app.services.payments.reconciliation import (
        ReconciliationError,
        reconcile_funding_unit,
    )

    try:
        reconciliation = reconcile_funding_unit(
            conn,
            funding_unit_id=instruction["unit_id"],
            actor_context=actor_context,
            gateway=gateway,
        )
    except ReconciliationError as exc:
        raise PaymentOperationError(str(exc)) from exc
    if reconciliation.outcome == "ambiguous":
        raise PaymentOperationError(
            "Release retry öncesi provider reconciliation ambiguous kaldı."
        )
    if reconciliation.outcome not in {"pool_created", "retry_eligible", "approved"}:
        raise PaymentOperationError("Release retry için provider durumu güvenli değil.")

    from backend.app.services.payments.release_coordinator import release_units

    result = release_units(
        conn,
        transaction_id=instruction["transaction_id"],
        unit_ids=(instruction["unit_id"],),
        gateway=gateway,
        actor_context=actor_context,
    )
    return {
        "instruction_id": instruction_id,
        "transaction_id": instruction["transaction_id"],
        "funding_unit_id": instruction["unit_id"],
        "status": (
            "confirmed"
            if instruction["unit_id"] in result.approved_unit_ids
            else "unknown"
            if instruction["unit_id"] in result.unknown_unit_ids
            else "failed"
            if instruction["unit_id"] in result.failed_unit_ids
            else "unchanged"
        ),
        "approved": instruction["unit_id"] in result.approved_unit_ids,
        "attempt_no": conn.execute(
            "SELECT MAX(attempt_no) FROM provider_operations "
            "WHERE funding_unit_id = ? AND operation_type = 'approve_pool_payment'",
            (instruction["unit_id"],),
        ).fetchone()[0],
    }
