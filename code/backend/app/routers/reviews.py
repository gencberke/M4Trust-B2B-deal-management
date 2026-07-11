"""Reviews uçları (§14, Plan 04 / Wave A / Faz 4B).

```
GET  /api/transactions/{transaction_id}/reviews
POST /api/reviews/{review_case_id}/actions
```

`main.py`'ye kayıt Berke'nindir. Yalnız donmuş `get_current_actor`/
`require_authenticated_user` + `require_csrf_protection` (Faz 3A'da donan,
diğer mutating uçlarda zaten kullanılan aynı dependency) kullanılır;
`services/access_control.py`'ye dokunulmaz.
"""

from __future__ import annotations

from sqlite3 import Connection
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.api.errors import ApiError
from backend.app.db import get_db
from backend.app.repositories import participants as participants_repo
from backend.app.repositories import reviews as reviews_repo
from backend.app.schemas.reviews import ReviewAction, ReviewActionRequest, ReviewCaseWithActions
from backend.app.services import participants as participants_service
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.auth import require_csrf_protection

router = APIRouter(tags=["reviews"])

_PLATFORM_REVIEW_ROLES = {"reviewer", "admin"}


def _is_platform_reviewer_or_admin(actor: ActorContext) -> bool:
    return actor.platform_role in _PLATFORM_REVIEW_ROLES


def _has_review_list_access(conn: Connection, transaction_id: str, actor: ActorContext) -> bool:
    """List: transaction'da aktif assignment sahibi user OR platform reviewer/admin."""
    if _is_platform_reviewer_or_admin(actor):
        return True
    return participants_service.has_transaction_access(conn, transaction_id, actor.user_id)


def _can_comment(conn: Connection, transaction_id: str, actor: ActorContext) -> bool:
    """Comment: transaction manager, participant approver, platform reviewer/admin."""
    if _is_platform_reviewer_or_admin(actor):
        return True
    return (
        participants_repo.get_active_assignment(conn, transaction_id, actor.user_id, role="manager")
        is not None
        or participants_repo.get_active_assignment(
            conn, transaction_id, actor.user_id, role="approver"
        )
        is not None
    )


@router.get("/api/transactions/{transaction_id}/reviews")
def list_reviews(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Connection = Depends(get_db),
) -> list[ReviewCaseWithActions]:
    if not _has_review_list_access(conn, transaction_id, actor):
        raise ApiError(
            status_code=403,
            code="REVIEW_ACCESS_DENIED",
            message="Bu işlemin review kayıtlarına erişiminiz yok.",
        )
    cases = review_service.list_cases(conn, transaction_id)
    return [
        ReviewCaseWithActions(case=case, actions=review_service.list_actions(conn, case.id))
        for case in cases
    ]


@router.post("/api/reviews/{review_case_id}/actions")
def submit_review_action(
    review_case_id: str,
    body: ReviewActionRequest,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> ReviewAction:
    case_row = reviews_repo.get_case_by_id(conn, review_case_id)
    if case_row is None:
        raise ApiError(
            status_code=404, code="REVIEW_CASE_NOT_FOUND", message="Review case bulunamadı."
        )
    transaction_id = case_row["transaction_id"]

    if body.action.value == "comment":
        authorized = _can_comment(conn, transaction_id, actor)
    else:
        authorized = _is_platform_reviewer_or_admin(actor)

    if not authorized:
        raise ApiError(
            status_code=403,
            code="REVIEW_ACTION_FORBIDDEN",
            message="Bu review action'ını yapmaya yetkiniz yok.",
        )

    payload: dict[str, str] = {}
    if body.comment is not None:
        payload["comment"] = body.comment
    if body.resolution_code is not None:
        payload["resolution_code"] = body.resolution_code

    try:
        return review_service.record_action(
            conn,
            case_id=review_case_id,
            actor_context=actor,
            action=body.action.value,
            payload=payload or None,
        )
    except review_service.ReviewCaseClosedError as exc:
        raise ApiError(status_code=409, code="REVIEW_CASE_CLOSED", message=str(exc)) from exc
    except review_service.ReviewActionForbiddenError as exc:
        raise ApiError(status_code=409, code="REVIEW_ACTION_NOT_ALLOWED", message=str(exc)) from exc
    except review_service.ReviewCommentRejectedError as exc:
        raise ApiError(status_code=400, code="REVIEW_COMMENT_REJECTED", message=str(exc)) from exc
    except review_service.ReviewResolutionPreconditionError as exc:
        raise ApiError(
            status_code=409, code="REVIEW_RESOLUTION_PRECONDITION_FAILED", message=str(exc)
        ) from exc
