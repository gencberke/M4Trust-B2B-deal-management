"""Human-controlled dispute lifecycle uçları (Plan 05 / Faz 5B).

```
POST /api/transactions/{transaction_id}/disputes            open_dispute
GET  /api/transactions/{transaction_id}/disputes             list_disputes
POST /api/disputes/{dispute_id}/actions                      record_dispute_action
```

`main.py`'ye kayıt Berke'nindir. Yalnız donmuş `get_current_actor`/
`require_authenticated_user`/`require_csrf_protection` kullanılır;
`services/access_control.py`'ye dokunulmaz. Dar `require_dispute_participant_
approver` kontrolü burada yaşar: yalnız aktif BUYER veya SELLER
participant'ını temsil eden `role=approver` assignment kabul edilir --
manager tek başına açamaz, viewer açamaz, platform reviewer ticari taraf
adına açamaz. Router provider ödeme modülü import etmez, kendi
`conn.commit()` çağırmaz.
"""

from __future__ import annotations

from sqlite3 import Connection, Row
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.errors import ApiError
from backend.app.db import get_db
from backend.app.repositories import participants as participants_repo
from backend.app.repositories.transactions import load_transaction
from backend.app.services import disputes as disputes_service
from backend.app.services import participants as participants_service
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.auth import require_csrf_protection

router = APIRouter(tags=["disputes"])

_PARTICIPANT_ROLES = ("buyer", "seller")
_PLATFORM_REVIEW_ROLES = {"reviewer", "admin"}


class DisputeOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milestone_id: str | None = None
    reason_code: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=2000)


class DisputeActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    comment: str | None = Field(default=None, max_length=2000)
    resolution_code: str | None = Field(default=None, max_length=64)
    evidence_id: str | None = None
    review_case_id: str | None = None


class DisputePublicView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    transaction_id: str
    milestone_id: str | None
    opened_by_user_id: str
    opened_by_entity_id: str
    reason_code: str
    description: str
    status: str
    resolution_code: str | None
    resolved_by_user_id: str | None
    created_at: str
    resolved_at: str | None


class DisputeActionPublicView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dispute_id: str
    actor_user_id: str
    acting_entity_id: str
    action: str
    evidence_id: str | None
    payload: dict | None
    created_at: str


def _to_public_view(dispute) -> DisputePublicView:
    return DisputePublicView(
        id=dispute.id,
        transaction_id=dispute.transaction_id,
        milestone_id=dispute.milestone_id,
        opened_by_user_id=dispute.opened_by_user_id,
        opened_by_entity_id=dispute.opened_by_entity_id,
        reason_code=dispute.reason_code,
        description=dispute.description,
        status=dispute.status,
        resolution_code=dispute.resolution_code,
        resolved_by_user_id=dispute.resolved_by_user_id,
        created_at=dispute.created_at,
        resolved_at=dispute.resolved_at,
    )


def _to_action_public_view(action) -> DisputeActionPublicView:
    return DisputeActionPublicView(
        id=action.id,
        dispute_id=action.dispute_id,
        actor_user_id=action.actor_user_id,
        acting_entity_id=action.acting_entity_id,
        action=action.action,
        evidence_id=action.evidence_id,
        payload=action.payload,
        created_at=action.created_at,
    )


def _require_account_transaction(conn: Connection, transaction_id: str) -> Row:
    transaction = load_transaction(conn, transaction_id)
    if transaction is None:
        raise ApiError(status_code=404, code="TRANSACTION_NOT_FOUND", message="İşlem bulunamadı.")
    if transaction["lifecycle_version"] != "account_v2":
        raise ApiError(
            status_code=409,
            code="LEGACY_DISPUTE_FORBIDDEN",
            message="Dispute yalnız account_v2 işlemler için kullanılabilir.",
        )
    return transaction


def require_dispute_participant_approver(conn: Connection, transaction_id: str, actor: ActorContext) -> None:
    """Dar yetki kapısı: yalnız aktif buyer/seller participant'ını temsil eden
    `role=approver` assignment dispute açabilir/action ekleyebilir.

    Manager tek başına, viewer, platform reviewer (participant/assignment'ı
    olmayan) veya sistem aktörleri hiçbir eşleşen assignment bulamayacağı için
    doğal olarak reddedilir. Kullanıcının TÜM aktif assignment'ları
    değerlendirilir (yalnız ilk bulunan satıra güvenilmez).
    """
    _require_account_transaction(conn, transaction_id)

    assignments = conn.execute(
        "SELECT * FROM transaction_assignments WHERE transaction_id = ? AND user_id = ? "
        "AND status = 'active' AND role = 'approver'",
        (transaction_id, actor.user_id),
    ).fetchall()

    for assignment in assignments:
        if assignment["legal_entity_id"] != actor.acting_entity_id:
            continue
        if assignment["participant_id"] is None:
            continue
        participant = participants_repo.get_participant_by_id(conn, assignment["participant_id"])
        if participant is not None and participant["role"] in _PARTICIPANT_ROLES:
            return

    raise ApiError(
        status_code=403,
        code="DISPUTE_PARTICIPANT_APPROVER_REQUIRED",
        message="Yalnız aktif buyer/seller participant approver'ı dispute açabilir/işlem yapabilir.",
    )


def require_dispute_action_authorization(
    conn: Connection, dispute, actor: ActorContext, action: str
) -> None:
    """Action'a göre participant/reviewer yetkisini seçer.

    Resolve, karşı taraf approver'ının tek başına release guard'ı kaldırmasını
    önlemek için opener veya platform reviewer/admin ile sınırlıdır.
    """
    if action == "resolve":
        is_opener = (
            dispute.opened_by_user_id == actor.user_id
            and dispute.opened_by_entity_id == actor.acting_entity_id
        )
        if is_opener or actor.platform_role in _PLATFORM_REVIEW_ROLES:
            _require_account_transaction(conn, dispute.transaction_id)
            return
        raise ApiError(
            status_code=403,
            code="DISPUTE_RESOLVE_FORBIDDEN",
            message="Dispute resolve yalnız opener veya platform reviewer/admin içindir.",
        )
    require_dispute_participant_approver(conn, dispute.transaction_id, actor)


@router.post("/api/transactions/{transaction_id}/disputes")
def open_dispute(
    transaction_id: str,
    body: DisputeOpenRequest,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> DisputePublicView:
    require_dispute_participant_approver(conn, transaction_id, actor)
    try:
        dispute = disputes_service.open_dispute(
            conn,
            transaction_id=transaction_id,
            milestone_id=body.milestone_id,
            reason_code=body.reason_code,
            description=body.description,
            actor_context=actor,
        )
    except disputes_service.DisputeAlreadyOpenError as exc:
        raise ApiError(status_code=409, code="DISPUTE_ALREADY_OPEN", message=str(exc)) from exc
    except disputes_service.DisputeContentRejectedError as exc:
        raise ApiError(status_code=400, code="DISPUTE_CONTENT_REJECTED", message=str(exc)) from exc
    return _to_public_view(dispute)


@router.get("/api/transactions/{transaction_id}/disputes")
def list_disputes(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Connection = Depends(get_db),
) -> list[DisputePublicView]:
    if not participants_service.has_transaction_access(conn, transaction_id, actor.user_id):
        raise ApiError(
            status_code=403, code="TRANSACTION_ACCESS_DENIED", message="Bu işlemde erişiminiz yok."
        )
    return [_to_public_view(d) for d in disputes_service.list_disputes(conn, transaction_id)]


@router.post("/api/disputes/{dispute_id}/actions")
def submit_dispute_action(
    dispute_id: str,
    body: DisputeActionRequest,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> DisputeActionPublicView:
    try:
        dispute = disputes_service.get_dispute(conn, dispute_id)
    except disputes_service.DisputeNotFoundError as exc:
        raise ApiError(status_code=404, code="DISPUTE_NOT_FOUND", message=str(exc)) from exc

    require_dispute_action_authorization(conn, dispute, actor, body.action)

    payload: dict[str, str] = {}
    if body.comment is not None:
        payload["comment"] = body.comment
    if body.resolution_code is not None:
        payload["resolution_code"] = body.resolution_code
    if body.review_case_id is not None:
        payload["review_case_id"] = body.review_case_id

    try:
        action = disputes_service.record_dispute_action(
            conn,
            dispute_id=dispute_id,
            actor_context=actor,
            action=body.action,
            payload=payload or None,
            evidence_id=body.evidence_id,
        )
    except disputes_service.DisputeAuthorizationError as exc:
        raise ApiError(status_code=403, code="DISPUTE_ACTION_FORBIDDEN", message=str(exc)) from exc
    except disputes_service.DisputeClosedError as exc:
        raise ApiError(status_code=409, code="DISPUTE_CLOSED", message=str(exc)) from exc
    except disputes_service.DisputeContentRejectedError as exc:
        raise ApiError(status_code=400, code="DISPUTE_CONTENT_REJECTED", message=str(exc)) from exc
    except disputes_service.DisputeCrossTransactionReferenceError as exc:
        raise ApiError(status_code=409, code="DISPUTE_CROSS_TRANSACTION_REFERENCE", message=str(exc)) from exc
    except ValueError as exc:
        raise ApiError(status_code=400, code="DISPUTE_ACTION_INVALID", message=str(exc)) from exc

    return _to_action_public_view(action)
