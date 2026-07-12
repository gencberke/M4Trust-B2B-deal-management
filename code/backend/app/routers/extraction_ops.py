"""Plan 07 extraction job recovery (Faz 7 follow-up remediation, Major 6)."""

from __future__ import annotations

from sqlite3 import Connection
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.api.errors import ApiError
from backend.app.db import get_db
from backend.app.services import extraction_recovery
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.auth import require_csrf_protection

router = APIRouter(tags=["extraction-operations"])


@router.post("/api/transactions/{transaction_id}/extraction/retry")
def retry_extraction(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> dict:
    try:
        result = extraction_recovery.retry_extraction(
            conn, transaction_id=transaction_id, actor_context=actor
        )
    except extraction_recovery.ExtractionRetryNotFoundError as exc:
        raise ApiError(status_code=404, code="EXTRACTION_RETRY_NOT_FOUND", message=str(exc)) from exc
    except extraction_recovery.ExtractionRetryForbiddenError as exc:
        raise ApiError(status_code=403, code="EXTRACTION_RETRY_FORBIDDEN", message=str(exc)) from exc
    except extraction_recovery.ExtractionRetryConflictError as exc:
        raise ApiError(
            status_code=409, code="EXTRACTION_RETRY_IN_PROGRESS", message=str(exc)
        ) from exc
    except extraction_recovery.ExtractionRetryError as exc:
        raise ApiError(status_code=409, code="EXTRACTION_RETRY_CONFLICT", message=str(exc)) from exc
    return result
