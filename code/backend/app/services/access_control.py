"""Plan 02'de donan, Faz 3A'da session actor ile genişletilen merkezi
actor/access-control kontratı.

`ActorContext`'in alan seti ve `get_current_actor`/`require_authenticated_user`/
`require_active_membership`'in public imza/davranışı (Plan 02 sonu freeze)
korunur — yalnız `actor_type`/`auth_method` kabul ettiği literal değerler
genişler ve `get_current_actor` artık geçerli bir session cookie'sini
capability token'dan önceliklice çözer. Legacy capability ve anonymous
davranışları değişmeden çalışmaya devam eder; Yusuf'un Plan 03B testleri
`app.dependency_overrides[get_current_actor] = stub_actor` kalıbıyla aynen
çalışır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request

from backend.app.db import connect
from backend.app.repositories.entities import get_active_membership
from backend.app.services.auth import SESSION_COOKIE_NAME, resolve_session_principal

_ACTING_ENTITY_HEADER = "X-Acting-Entity-ID"


@dataclass(frozen=True, slots=True)
class ActorContext:
    actor_type: Literal["anonymous", "legacy_capability", "user"]
    user_id: str | None = None
    acting_entity_id: str | None = None
    platform_role: str | None = None
    transaction_assignment_role: str | None = None
    participant_role: str | None = None
    request_id: str | None = None
    auth_method: Literal["none", "legacy_capability", "session", "demo_seed"] = "none"


def _resolve_session_actor(request: Request, *, request_id: str | None) -> ActorContext | None:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        return None

    conn = connect()
    try:
        principal = resolve_session_principal(conn, raw_token)
        if principal is None:
            return None

        acting_entity_id: str | None = None
        requested_entity_id = request.headers.get(_ACTING_ENTITY_HEADER)
        if requested_entity_id:
            # Header'daki entity, session user'ının gerçek aktif üyeliğiyle
            # doğrulanmadan `acting_entity_id`'ye yazılmaz.
            membership = get_active_membership(
                conn, user_id=principal.user_id, legal_entity_id=requested_entity_id
            )
            if membership is not None:
                acting_entity_id = requested_entity_id
    finally:
        conn.close()

    return ActorContext(
        actor_type="user",
        user_id=principal.user_id,
        acting_entity_id=acting_entity_id,
        platform_role=principal.platform_role,
        request_id=request_id,
        auth_method="session",
    )


async def get_current_actor(request: Request) -> ActorContext:
    request_id = getattr(request.state, "request_id", None)

    session_actor = _resolve_session_actor(request, request_id=request_id)
    if session_actor is not None:
        return session_actor

    capability_present = any(
        request.query_params.get(name)
        for name in ("token", "buyer_token", "seller_token", "manager_token")
    )
    if capability_present:
        return ActorContext(
            actor_type="legacy_capability",
            request_id=request_id,
            auth_method="legacy_capability",
        )
    return ActorContext(actor_type="anonymous", request_id=request_id)


def require_authenticated_user(
    actor: Annotated[ActorContext, Depends(get_current_actor)],
) -> ActorContext:
    if actor.user_id is None:
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli.")
    return actor


def require_active_membership(
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
) -> ActorContext:
    if actor.acting_entity_id is None:
        raise HTTPException(status_code=403, detail="Aktif üyelik gerekli.")
    return actor
