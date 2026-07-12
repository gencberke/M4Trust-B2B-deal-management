"""Account fulfillment schedule projection routes."""

from __future__ import annotations

from sqlite3 import Connection
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.api.errors import ApiError
from backend.app.db import get_db
from backend.app.repositories.transactions import load_transaction
from backend.app.schemas.projections import MilestoneFundingProjection
from backend.app.services import fulfillment_projection
from backend.app.services import participants as participants_service
from backend.app.services.access_control import ActorContext, require_authenticated_user

router = APIRouter(tags=["fulfillment"])


@router.get(
    "/api/transactions/{transaction_id}/milestones",
    response_model=MilestoneFundingProjection,
)
def get_transaction_milestones(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Connection = Depends(get_db),
) -> MilestoneFundingProjection:
    """Return current-package milestones and funding units for an assignment."""

    transaction = load_transaction(conn, transaction_id)
    if transaction is None:
        raise ApiError(status_code=404, code="TRANSACTION_NOT_FOUND", message="İşlem bulunamadı.")
    if transaction["lifecycle_version"] != "account_v2":
        raise ApiError(
            status_code=409,
            code="LEGACY_FULFILLMENT_PROJECTION_FORBIDDEN",
            message="Milestone projection yalnız account_v2 işlemler için kullanılabilir.",
        )
    if actor.user_id is None or not participants_service.has_transaction_access(
        conn, transaction_id, actor.user_id
    ):
        raise ApiError(
            status_code=403,
            code="TRANSACTION_ACCESS_DENIED",
            message="Bu işlemde erişiminiz yok.",
        )
    return fulfillment_projection.project_transaction_milestones(conn, transaction_id)
