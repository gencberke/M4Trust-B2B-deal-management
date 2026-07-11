"""Entities router — legal entity create/list/detail/patch (Faz 3A, §14).

Bu router `main.py`'ye Plan 03 integration checkpoint'inde kaydedilir.
Ciphertext/HMAC hiçbir response'a girmez — yalnız `EntityPublic` projection
döner.
"""

from __future__ import annotations

import json
from sqlite3 import Connection
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.repositories import entities as entities_repo
from backend.app.schemas.identity import EntityCreateRequest, EntityPublic, EntityUpdateRequest
from backend.app.services import identity as identity_service
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.auth import require_csrf_protection

router = APIRouter(prefix="/api/entities", tags=["entities"])


def _settings() -> Settings:
    return Settings.from_env()


def _entity_public(row, *, my_role: str) -> EntityPublic:
    address_json = json.loads(row["address_json"]) if row["address_json"] else None
    return EntityPublic(
        id=row["id"],
        entity_type=row["entity_type"],
        legal_name=row["legal_name"],
        tax_identifier_type=row["tax_identifier_type"],
        tax_identifier_last4=row["tax_identifier_last4"],
        tax_office=row["tax_office"],
        address_json=address_json,
        verification_status=row["verification_status"],
        my_role=my_role,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("", status_code=201, response_model=EntityPublic)
def create_entity(
    body: EntityCreateRequest,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Annotated[Connection, Depends(get_db)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
) -> EntityPublic:
    settings = _settings()
    entity_id = identity_service.create_entity(
        conn,
        entity_type=body.entity_type.value,
        legal_name=body.legal_name,
        tax_identifier_type=body.tax_identifier_type.value,
        raw_tax_identifier=body.tax_identifier,
        tax_office=body.tax_office,
        address_json=body.address_json,
        created_by_user_id=actor.user_id,
        settings=settings,
    )
    row = entities_repo.get_entity_by_id(conn, entity_id)
    return _entity_public(row, my_role="owner")


@router.get("", response_model=list[EntityPublic])
def list_entities(
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Annotated[Connection, Depends(get_db)],
) -> list[EntityPublic]:
    rows = entities_repo.list_entities_for_user(conn, actor.user_id)
    return [_entity_public(row, my_role=row["my_role"]) for row in rows]


@router.get("/{entity_id}", response_model=EntityPublic)
def get_entity(
    entity_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Annotated[Connection, Depends(get_db)],
) -> EntityPublic:
    membership = identity_service.require_membership(
        conn, user_id=actor.user_id, entity_id=entity_id
    )
    row = entities_repo.get_entity_by_id(conn, entity_id)
    return _entity_public(row, my_role=membership["role"])


@router.patch("/{entity_id}", response_model=EntityPublic)
def patch_entity(
    entity_id: str,
    body: EntityUpdateRequest,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Annotated[Connection, Depends(get_db)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
) -> EntityPublic:
    membership = identity_service.require_membership(
        conn, user_id=actor.user_id, entity_id=entity_id
    )
    identity_service.require_write_role(membership)
    identity_service.update_entity(
        conn,
        entity_id=entity_id,
        legal_name=body.legal_name,
        tax_office=body.tax_office,
        address_json_provided="address_json" in body.model_fields_set,
        address_json=body.address_json,
    )
    row = entities_repo.get_entity_by_id(conn, entity_id)
    return _entity_public(row, my_role=membership["role"])
