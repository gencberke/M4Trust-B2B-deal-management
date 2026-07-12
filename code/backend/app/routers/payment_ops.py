"""Plan 07 payment operasyonları: reconcile, retry, reversal ve trace."""

from __future__ import annotations

from sqlite3 import Connection
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.errors import ApiError
from backend.app.db import get_db
from backend.app.repositories import payment_resolutions as resolutions_repo
from backend.app.repositories.transactions import load_transaction
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.auth import require_csrf_protection
from backend.app.services import participants as participants_service
from backend.app.schemas.payments import PaymentResolutionListPublic, PaymentResolutionPublic
from backend.app.services.payments import payment_operations
from backend.app.services.payments.reconciliation import (
    ReconciliationError,
    reconcile_funding_unit,
)

router = APIRouter(tags=["payment-operations"])

_PLATFORM_ROLES = frozenset({"reviewer", "admin"})


class ResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str | None = Field(default=None, max_length=128)


def _is_platform_actor(actor: ActorContext) -> bool:
    return actor.platform_role in _PLATFORM_ROLES


def _require_manager_or_platform(
    conn: Connection, *, transaction_id: str, actor: ActorContext
) -> None:
    if _is_platform_actor(actor):
        return
    if payment_operations.actor_is_transaction_manager(
        conn, transaction_id=transaction_id, actor=actor
    ):
        return
    raise ApiError(
        status_code=403,
        code="PAYMENT_OPERATION_FORBIDDEN",
        message="Bu payment operasyonu için manager veya platform reviewer yetkisi gerekir.",
    )


def _resolution_view(conn: Connection, row) -> dict:
    return {
        "id": row["id"],
        "transaction_id": row["transaction_id"],
        "funding_unit_id": row["funding_unit_id"],
        "review_case_id": row["review_case_id"],
        "operation_type": row["operation_type"],
        "status": row["status"],
        "idempotency_key": row["idempotency_key"],
        "requested_by_user_id": row["requested_by_user_id"],
        "requested_by_entity_id": row["requested_by_entity_id"],
        "executed_by_user_id": row["executed_by_user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "updated_at": row["updated_at"],
        "approvals": [
            {
                "participant_role": approval["participant_role"],
                "user_id": approval["user_id"],
                "acting_entity_id": approval["acting_entity_id"],
                "created_at": approval["created_at"],
            }
            for approval in resolutions_repo.list_approvals(conn, row["id"])
        ],
    }


def _require_transaction_assignment(
    conn: Connection, *, transaction_id: str, actor: ActorContext
) -> None:
    transaction = load_transaction(conn, transaction_id)
    if transaction is None:
        raise ApiError(status_code=404, code="TRANSACTION_NOT_FOUND", message="Ä°ÅŸlem bulunamadÄ±.")
    if transaction["lifecycle_version"] != "account_v2":
        raise ApiError(
            status_code=409,
            code="PAYMENT_RESOLUTION_LEGACY_UNSUPPORTED",
            message="Payment resolution projection yalnÄ±z account_v2 iÅŸlemler iÃ§in kullanÄ±labilir.",
        )
    if not _is_platform_actor(actor) and not participants_service.has_transaction_access_for_actor(
        conn, transaction_id, actor
    ):
        raise ApiError(
            status_code=403,
            code="TRANSACTION_ACCESS_DENIED",
            message="Bu iÅŸlemde eriÅŸiminiz yok.",
        )


@router.post("/api/transactions/{transaction_id}/payments/reconcile")
def reconcile_transaction_payments(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> dict:
    transaction = conn.execute(
        "SELECT id FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    if transaction is None:
        raise ApiError(status_code=404, code="TRANSACTION_NOT_FOUND", message="İşlem bulunamadı.")
    _require_manager_or_platform(conn, transaction_id=transaction_id, actor=actor)
    units = conn.execute(
        "SELECT id FROM funding_units WHERE transaction_id = ? "
        "AND status IN ('pool_creation_unknown', 'approval_unknown') "
        "ORDER BY sequence ASC, id ASC",
        (transaction_id,),
    ).fetchall()
    results = []
    for unit in units:
        try:
            result = reconcile_funding_unit(
                conn, funding_unit_id=unit["id"], actor_context=actor
            )
        except ReconciliationError as exc:
            raise ApiError(
                status_code=409,
                code="PAYMENT_RECONCILE_CONFLICT",
                message=str(exc),
            ) from exc
        results.append(
            {
                "funding_unit_id": result.funding_unit_id,
                "outcome": result.outcome,
                "status": result.local_status,
                "provider_status": result.provider_status,
                "retry_eligible": result.retry_eligible,
                "review_opened": result.review_opened,
            }
        )
    return {"transaction_id": transaction_id, "results": results}


@router.post("/api/release-instructions/{instruction_id}/retry")
def retry_release_instruction(
    instruction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> dict:
    row = conn.execute(
        "SELECT transaction_id FROM release_instructions ri "
        "JOIN funding_units fu ON fu.id = ri.funding_unit_id WHERE ri.id = ?",
        (instruction_id,),
    ).fetchone()
    if row is None:
        raise ApiError(
            status_code=404, code="RELEASE_INSTRUCTION_NOT_FOUND", message="Release instruction bulunamadı."
        )
    _require_manager_or_platform(conn, transaction_id=row["transaction_id"], actor=actor)
    try:
        return payment_operations.retry_release_instruction(
            conn, instruction_id=instruction_id, actor_context=actor
        )
    except payment_operations.PaymentOperationError as exc:
        raise ApiError(status_code=409, code="PAYMENT_RETRY_CONFLICT", message=str(exc)) from exc


def _request_resolution(
    *,
    funding_unit_id: str,
    operation_type: str,
    body: ResolutionRequest,
    idempotency_header: str | None,
    actor: ActorContext,
    conn: Connection,
) -> dict:
    key = idempotency_header or body.idempotency_key
    try:
        row = payment_operations.request_resolution(
            conn,
            funding_unit_id=funding_unit_id,
            operation_type=operation_type,
            actor_context=actor,
            idempotency_key=key,
        )
    except payment_operations.PaymentOperationError as exc:
        raise ApiError(status_code=409, code="PAYMENT_RESOLUTION_CONFLICT", message=str(exc)) from exc
    return _resolution_view(conn, row)


@router.post("/api/funding-units/{funding_unit_id}/undo-request")
def request_undo(
    funding_unit_id: str,
    body: ResolutionRequest,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    conn: Connection = Depends(get_db),
) -> dict:
    return _request_resolution(
        funding_unit_id=funding_unit_id,
        operation_type="undo_approval",
        body=body,
        idempotency_header=idempotency_header,
        actor=actor,
        conn=conn,
    )


@router.post("/api/funding-units/{funding_unit_id}/refund-request")
def request_refund(
    funding_unit_id: str,
    body: ResolutionRequest,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    conn: Connection = Depends(get_db),
) -> dict:
    return _request_resolution(
        funding_unit_id=funding_unit_id,
        operation_type="refund",
        body=body,
        idempotency_header=idempotency_header,
        actor=actor,
        conn=conn,
    )


@router.get(
    "/api/transactions/{transaction_id}/payment-resolutions",
    response_model=PaymentResolutionListPublic,
)
def list_payment_resolutions(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Connection = Depends(get_db),
) -> PaymentResolutionListPublic:
    """Assignment-scoped payment resolution list with bilateral approvals."""

    _require_transaction_assignment(conn, transaction_id=transaction_id, actor=actor)
    return PaymentResolutionListPublic(
        transaction_id=transaction_id,
        resolutions=[
            _resolution_view(conn, row)
            for row in resolutions_repo.list_for_transaction(conn, transaction_id)
        ],
    )


@router.get(
    "/api/transactions/{transaction_id}/payment-resolutions/{resolution_id}",
    response_model=PaymentResolutionPublic,
)
def get_payment_resolution(
    transaction_id: str,
    resolution_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Connection = Depends(get_db),
) -> PaymentResolutionPublic:
    """Assignment-scoped resolution detail; cross-transaction IDs are opaque."""

    _require_transaction_assignment(conn, transaction_id=transaction_id, actor=actor)
    row = resolutions_repo.get_by_id(conn, resolution_id)
    if row is None or row["transaction_id"] != transaction_id:
        raise ApiError(
            status_code=404,
            code="PAYMENT_RESOLUTION_NOT_FOUND",
            message="Payment resolution bulunamadÄ±.",
        )
    return PaymentResolutionPublic.model_validate(_resolution_view(conn, row))


@router.post("/api/payment-resolutions/{resolution_id}/approvals")
def approve_payment_resolution(
    resolution_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> dict:
    try:
        row = payment_operations.approve_resolution(
            conn, resolution_id=resolution_id, actor_context=actor
        )
    except payment_operations.PaymentOperationError as exc:
        raise ApiError(status_code=403, code="PAYMENT_RESOLUTION_APPROVAL_FORBIDDEN", message=str(exc)) from exc
    return _resolution_view(conn, row)


@router.post("/api/payment-resolutions/{resolution_id}/execute")
def execute_payment_resolution(
    resolution_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> dict:
    try:
        result = payment_operations.execute_resolution(
            conn, resolution_id=resolution_id, actor_context=actor
        )
    except payment_operations.PaymentOperationError as exc:
        raise ApiError(status_code=409, code="PAYMENT_RESOLUTION_EXECUTION_CONFLICT", message=str(exc)) from exc
    return {
        "resolution_id": result.resolution_id,
        "funding_unit_id": result.funding_unit_id,
        "operation_type": result.operation_type,
        "status": result.status,
        "provider_outcome": result.provider_outcome,
        "provider_code": result.provider_code,
    }


@router.get("/api/transactions/{transaction_id}/payment-trace")
def payment_trace(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Connection = Depends(get_db),
) -> dict:
    transaction = conn.execute(
        "SELECT lifecycle_version FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    if transaction is None:
        raise ApiError(status_code=404, code="TRANSACTION_NOT_FOUND", message="İşlem bulunamadı.")
    _require_manager_or_platform(conn, transaction_id=transaction_id, actor=actor)
    if transaction["lifecycle_version"] != "account_v2":
        raise ApiError(
            status_code=409,
            code="PAYMENT_TRACE_LEGACY_UNSUPPORTED",
            message="Payment trace yalnız account_v2 payment lifecycle için kullanılabilir.",
        )
    return {
        "transaction_id": transaction_id,
        "operations": payment_operations.get_payment_trace(conn, transaction_id),
    }
