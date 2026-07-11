"""Account ratification package + ratification uçları (Plan 04 / Wave B / Faz 4E, §14).

```
POST /api/transactions/{transaction_id}/ratification-packages           build/open current package
GET  /api/transactions/{transaction_id}/ratification-packages/current   iki tarafın da gördüğü canonical projeksiyon
POST /api/ratification-packages/{package_id}/ratifications              participant approver ratification'ı
```

`main.py`'ye kayıt Berke'nindir. Router kendi canonical JSON'unu veya funding
planını üretmez — donmuş `RatificationPackageService`/`FundingCoordinator`
seam'lerini kullanır; provider hiçbir zaman doğrudan çağrılmaz.
"""

from __future__ import annotations

import hashlib
import json
import re
from sqlite3 import Connection
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.app.api.errors import ApiError
from backend.app.db import get_db
from backend.app.schemas.payments import FundingScheduleSpec
from backend.app.schemas.ratification import RatificationOutcome, RatificationPackagePublicView
from backend.app.services import participants as participants_service
from backend.app.services import ratifications as ratifications_service
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.auth import require_csrf_protection
from backend.app.services.payments.domain import MOKA_STANDARD_PROFILE
from backend.app.services.payments.funding_coordinator import FundingCoordinatorError
from backend.app.services.ratification_package import (
    PackageConflictError,
    PackageIntegrityError,
    PackageNotFoundError,
    PackageNotReadyError,
    build_current_package,
    get_current,
    open_package,
    supersede_if_inputs_changed,
)

router = APIRouter(tags=["ratifications"])

_UA_MAX_LENGTH = 160
_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


class RatificationPackageBuildRequest(BaseModel):
    funding_schedule_spec: FundingScheduleSpec = FundingScheduleSpec()


def _require_access(conn: Connection, transaction_id: str, actor: ActorContext) -> None:
    if actor.user_id is None or not participants_service.has_transaction_access(
        conn, transaction_id, actor.user_id
    ):
        raise ApiError(
            status_code=403,
            code="TRANSACTION_ACCESS_DENIED",
            message="Bu işlemde erişiminiz yok.",
        )


def _to_public_view(package) -> RatificationPackagePublicView:
    return RatificationPackagePublicView(
        id=package.id,
        transaction_id=package.transaction_id,
        version=package.version,
        status=package.status,
        package_hash=package.package_hash,
        canonical_payload=json.loads(package.canonical_payload_json),
        created_at=package.created_at,
        opened_at=package.opened_at,
        completed_at=package.completed_at,
    )


def _raise_package_api_error(exc: Exception) -> None:
    """Package domain hatalarını standart `ApiError` zarfına çevirir (tek yerde)."""
    if isinstance(exc, (PackageNotReadyError, PackageConflictError)):
        raise ApiError(status_code=409, code=exc.reason_code, message=str(exc)) from exc
    if isinstance(exc, PackageIntegrityError):
        raise ApiError(status_code=409, code="PACKAGE_INTEGRITY_FAILED", message=str(exc)) from exc
    if isinstance(exc, PackageNotFoundError):
        raise ApiError(status_code=404, code="PACKAGE_NOT_FOUND", message=str(exc)) from exc
    raise exc


def _client_ip_hash(request: Request) -> str | None:
    client = request.client
    if client is None or not client.host:
        return None
    return hashlib.sha256(client.host.encode("utf-8")).hexdigest()


def _user_agent_summary(request: Request) -> str | None:
    raw = request.headers.get("user-agent")
    if not raw:
        return None
    cleaned = _WHITESPACE_RE.sub(" ", _CONTROL_CHARS_RE.sub("", raw)).strip()
    return cleaned[:_UA_MAX_LENGTH] or None


@router.post("/api/transactions/{transaction_id}/ratification-packages")
def build_and_open_ratification_package(
    transaction_id: str,
    body: RatificationPackageBuildRequest,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> RatificationPackagePublicView:
    _require_access(conn, transaction_id, actor)
    try:
        package = build_current_package(
            conn,
            transaction_id=transaction_id,
            funding_schedule_spec=body.funding_schedule_spec,
            capabilities=MOKA_STANDARD_PROFILE,
            actor_context=actor,
        )
    except PackageConflictError as exc:
        if exc.reason_code != "PACKAGE_INPUTS_CHANGED":
            _raise_package_api_error(exc)
        # Girdiler (rule revision/policy/participant) değişti -- donmuş amendment
        # seam'i üzerinden yeni version'ı superseded edip güncel package'ı üretir.
        # Aksi halde ilk (yanlış) package'ı oluşturan herhangi bir transaction-access
        # sahibi akışı kalıcı olarak kilitleyebilirdi (düzeltilmiş schedule'a giden
        # API yolu yoktu).
        try:
            package = supersede_if_inputs_changed(
                conn,
                transaction_id=transaction_id,
                funding_schedule_spec=body.funding_schedule_spec,
                capabilities=MOKA_STANDARD_PROFILE,
                actor_context=actor,
            )
        except (PackageNotReadyError, PackageConflictError, PackageIntegrityError, PackageNotFoundError) as inner_exc:
            _raise_package_api_error(inner_exc)
    except (PackageNotReadyError, PackageIntegrityError, PackageNotFoundError) as exc:
        _raise_package_api_error(exc)

    try:
        package = open_package(conn, package_id=package.id, actor_context=actor)
    except (PackageConflictError, PackageIntegrityError, PackageNotFoundError) as exc:
        _raise_package_api_error(exc)

    return _to_public_view(package)


@router.get("/api/transactions/{transaction_id}/ratification-packages/current")
def get_current_ratification_package(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Connection = Depends(get_db),
) -> RatificationPackagePublicView:
    _require_access(conn, transaction_id, actor)
    package = get_current(conn, transaction_id)
    if package is None:
        raise ApiError(
            status_code=404, code="PACKAGE_NOT_FOUND", message="Current package bulunamadı."
        )
    return _to_public_view(package)


@router.post("/api/ratification-packages/{package_id}/ratifications")
def submit_ratification(
    package_id: str,
    request: Request,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> RatificationOutcome:
    try:
        outcome = ratifications_service.create_ratification(
            conn,
            package_id=package_id,
            actor_context=actor,
            auth_method=actor.auth_method,
            client_ip_hash=_client_ip_hash(request),
            user_agent_summary=_user_agent_summary(request),
        )
    except ratifications_service.RatificationPackageNotFoundError as exc:
        raise ApiError(status_code=404, code="PACKAGE_NOT_FOUND", message=str(exc)) from exc
    except ratifications_service.RatificationAuthorizationError as exc:
        raise ApiError(status_code=403, code="RATIFICATION_NOT_AUTHORIZED", message=str(exc)) from exc
    except ratifications_service.RatificationConflictError as exc:
        raise ApiError(status_code=409, code=exc.reason_code, message=str(exc)) from exc
    except FundingCoordinatorError as exc:
        raise ApiError(status_code=409, code="FUNDING_COORDINATOR_CONFLICT", message=str(exc)) from exc
    return outcome
