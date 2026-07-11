"""Plan 02'de donan merkezi actor/access-control kontratı.

Bu aşama session veya membership uygulamaz; yalnız anonim ve mevcut capability
link isteklerini temsil eder. Fonksiyonlar production router'larına henüz
bağlanmaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request


@dataclass(frozen=True, slots=True)
class ActorContext:
    actor_type: Literal["anonymous", "legacy_capability"]
    user_id: str | None = None
    acting_entity_id: str | None = None
    platform_role: str | None = None
    transaction_assignment_role: str | None = None
    participant_role: str | None = None
    request_id: str | None = None
    auth_method: Literal["none", "legacy_capability"] = "none"


async def get_current_actor(request: Request) -> ActorContext:
    request_id = getattr(request.state, "request_id", None)
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
