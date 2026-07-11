"""Participant uçları (§14, Plan 03 / Faz 3B).

```
GET  /api/transactions/{id}/participants              list (transaction access sahibi)
PUT  /api/transactions/{id}/participants/me/profile    declared snapshot
POST /api/transactions/{id}/participants/me/confirm    confirmed snapshot + confirmed_at
```

`main.py`'ye kayıt Berke'nindir. Yalnız donmuş `get_current_actor`/
`require_authenticated_user` dependency'lerini kullanır.
"""

from __future__ import annotations

from sqlite3 import Connection
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.api.errors import ApiError
from backend.app.db import get_db
from backend.app.schemas.participants import (
    Participant,
    ParticipantPublicView,
    ProfileUpdateRequest,
)
from backend.app.services import participants as participants_service
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.auth import require_csrf_protection

router = APIRouter(prefix="/api/transactions/{transaction_id}/participants", tags=["participants"])


def _display_name(participant) -> str | None:
    snapshot = (
        participant.confirmed_snapshot or participant.declared_snapshot or participant.extracted_snapshot
    )
    return snapshot.name if snapshot is not None else None


def _to_public_view(participant) -> ParticipantPublicView:
    return ParticipantPublicView(
        id=participant.id,
        role=participant.role,
        status=participant.status,
        display_name=_display_name(participant),
        confirmed=participant.confirmed_at is not None,
        confirmed_at=participant.confirmed_at,
    )


@router.get("")
def list_participants(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Connection = Depends(get_db),
) -> list[ParticipantPublicView]:
    if not participants_service.has_transaction_access(conn, transaction_id, actor.user_id):
        raise ApiError(
            status_code=403,
            code="TRANSACTION_ACCESS_DENIED",
            message="Bu işlemde erişiminiz yok.",
        )
    participants = participants_service.list_participants(conn, transaction_id)
    return [_to_public_view(p) for p in participants]


@router.put("/me/profile")
def update_my_profile(
    transaction_id: str,
    body: ProfileUpdateRequest,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> Participant:
    try:
        return participants_service.update_declared_profile(
            conn, transaction_id, actor, body.snapshot.model_dump()
        )
    except participants_service.ParticipantNotFoundError as exc:
        raise ApiError(status_code=404, code="PARTICIPANT_NOT_FOUND", message=str(exc)) from exc
    except participants_service.ParticipantConflictError as exc:
        raise ApiError(status_code=409, code="PARTICIPANT_CONFIRMED_LOCKED", message=str(exc)) from exc


@router.post("/me/confirm")
def confirm_my_profile(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> Participant:
    try:
        return participants_service.confirm_my_profile(conn, transaction_id, actor)
    except participants_service.ParticipantNotFoundError as exc:
        raise ApiError(status_code=404, code="PARTICIPANT_NOT_FOUND", message=str(exc)) from exc
    except participants_service.ParticipantConflictError as exc:
        raise ApiError(status_code=409, code="PARTICIPANT_CONFIRM_CONFLICT", message=str(exc)) from exc
