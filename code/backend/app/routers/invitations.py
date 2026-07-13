"""Invitation uçları (§14, Plan 03 / Faz 3B).

```
POST /api/transactions/{id}/invitations           create (yalnız manager/creator)
GET  /api/invitations/{token}/preview             auth'suz, PII'siz güvenli önizleme
POST /api/invitations/{token}/accept              accept (authenticated user)
POST /api/transactions/{id}/invitations/{invite_id}/revoke  revoke (yalnız manager/creator)
```

`main.py`'ye kayıt Berke'nindir (router include + `NotificationProvider`/`get_db`
enjeksiyonu bağlanır). Bu router yalnız donmuş `get_current_actor`/
`require_authenticated_user` dependency'lerini kullanır; `access_control.py`'ye
dokunmaz.
"""

from __future__ import annotations

from sqlite3 import Connection
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from backend.app.api.errors import ApiError
from backend.app.db import get_db
from backend.app.schemas.participants import (
    InvitationAcceptRequest,
    InvitationCreateRequest,
    InvitationCreateResult,
    InvitationPreview,
    Participant,
)
from backend.app.services import invitations as invitations_service
from backend.app.services import participants as participants_service
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.auth import require_csrf_protection
from backend.app.services.notifications import NotificationProvider, make_notification_provider

router = APIRouter(tags=["invitations"])

# Gerçek NotificationProvider seçimi (env-tabanlı) main.py wiring'ine aittir;
# bu fazda yalnız fake mevcuttur (ARCHITECTURE §3 adapter+fake ilkesi).
def get_notification_provider() -> NotificationProvider:
    return make_notification_provider()


def _build_invite_link(request: Request, token: str) -> str:
    return f"/api/invitations/{token}/accept"


@router.post("/api/transactions/{transaction_id}/invitations")
def create_invitation(
    transaction_id: str,
    body: InvitationCreateRequest,
    request: Request,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    notification_provider: Annotated[NotificationProvider, Depends(get_notification_provider)],
    conn: Connection = Depends(get_db),
) -> InvitationCreateResult:
    try:
        created = invitations_service.create_invitation(
            conn,
            transaction_id,
            body.participant_role.value,
            body.invited_email.strip().lower(),
            actor,
            notification_provider,
            invite_link_builder=lambda raw_token: _build_invite_link(request, raw_token),
        )
    except invitations_service.InvitationAuthorizationError as exc:
        raise ApiError(status_code=403, code="INVITATION_FORBIDDEN", message=str(exc)) from exc
    except invitations_service.InvitationRoleAlreadyBoundError as exc:
        raise ApiError(status_code=409, code="INVITATION_ROLE_ALREADY_BOUND", message=str(exc)) from exc

    return InvitationCreateResult(
        invitation_id=created.invitation_id,
        participant_role=body.participant_role,
        expires_at=created.expires_at,
        invite_link=_build_invite_link(request, created.raw_token),
    )


@router.get("/api/invitations/{token}/preview")
def preview_invitation(token: str, conn: Connection = Depends(get_db)) -> InvitationPreview:
    try:
        return invitations_service.preview_invitation(conn, token)
    except invitations_service.InvitationNotFoundError as exc:
        raise ApiError(status_code=404, code="INVITATION_NOT_FOUND", message=str(exc)) from exc


@router.post("/api/invitations/{token}/accept")
def accept_invitation(
    token: str,
    body: InvitationAcceptRequest,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> Participant:
    try:
        return participants_service.accept_invitation(conn, token, actor, body.legal_entity_id)
    except participants_service.ParticipantAuthorizationError as exc:
        raise ApiError(status_code=403, code="INVITATION_FORBIDDEN", message=str(exc)) from exc
    except participants_service.InvitationNotFoundError as exc:
        raise ApiError(status_code=404, code="INVITATION_NOT_FOUND", message=str(exc)) from exc
    except participants_service.InvitationEmailMismatchError as exc:
        raise ApiError(status_code=403, code="INVITATION_EMAIL_MISMATCH", message=str(exc)) from exc
    except participants_service.InvitationNotAcceptableError as exc:
        raise ApiError(status_code=409, code="INVITATION_NOT_ACCEPTABLE", message=str(exc)) from exc
    except participants_service.ParticipantConflictError as exc:
        raise ApiError(status_code=409, code="PARTICIPANT_CONFLICT", message=str(exc)) from exc


@router.post("/api/transactions/{transaction_id}/invitations/{invitation_id}/revoke")
def revoke_invitation(
    transaction_id: str,
    invitation_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> dict:
    try:
        invitations_service.revoke_invitation(conn, transaction_id, invitation_id, actor)
    except invitations_service.InvitationAuthorizationError as exc:
        raise ApiError(status_code=403, code="INVITATION_FORBIDDEN", message=str(exc)) from exc
    except invitations_service.InvitationNotFoundError as exc:
        raise ApiError(status_code=404, code="INVITATION_NOT_FOUND", message=str(exc)) from exc
    except invitations_service.InvitationNotRevocableError as exc:
        raise ApiError(status_code=409, code="INVITATION_NOT_REVOCABLE", message=str(exc)) from exc
    return {"status": "revoked"}
