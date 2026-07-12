"""Evidence bundle ve snapshot uçları.

Account uçları session + transaction assignment erişimiyle korunur. Legacy
capability GET'i Plan 05 boyunca flag arkasında tutulur; artık snapshot
oluşturmaz ve yeni read-only bundle uçlarına yönlendiren deprecation bilgisi
taşır.
"""

from __future__ import annotations

from sqlite3 import Connection
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from backend.app.api.errors import ApiError
from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.repositories.transactions import load_transaction
from backend.app.routers.transactions import resolve_manager, resolve_party
from backend.app.services import audit
from backend.app.services import evidence as evidence_service
from backend.app.services import participants as participants_service
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.auth import require_csrf_protection

router = APIRouter(prefix="/api/transactions", tags=["evidence"])


def _require_legacy_capability_enabled(settings: Settings) -> None:
    if not settings.legacy_capability_access_enabled:
        raise HTTPException(
            status_code=403,
            detail="Legacy capability erişimi kapalı; account evidence-bundle endpoint'ini kullanın.",
        )


def _require_account_transaction_access(
    conn: Connection, transaction_id: str, actor: ActorContext
) -> None:
    row = load_transaction(conn, transaction_id)
    if row is None:
        raise ApiError(status_code=404, code="TRANSACTION_NOT_FOUND", message="İşlem bulunamadı.")
    if actor.user_id is None or not participants_service.has_transaction_access(
        conn, transaction_id, actor.user_id
    ):
        raise ApiError(
            status_code=403,
            code="TRANSACTION_ACCESS_DENIED",
            message="Bu işlemde erişiminiz yok.",
        )


def _snapshot_response(snapshot_hash: str, bundle: dict, *, created: bool) -> dict:
    return {
        "snapshot_id": snapshot_hash,
        "snapshot_hash": snapshot_hash,
        "created": created,
        "bundle": bundle,
    }


@router.get("/{transaction_id}/evidence-bundle")
def get_evidence_bundle(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Connection = Depends(get_db),
) -> dict:
    """Account için side-effect-free current bundle projection'ı."""

    _require_account_transaction_access(conn, transaction_id, actor)
    return evidence_service.build_bundle(conn, transaction_id)


@router.post("/{transaction_id}/evidence-snapshots")
def create_evidence_snapshot(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> dict:
    """İnsan/API tarafından açıkça istenen immutable evidence snapshot'ı."""

    _require_account_transaction_access(conn, transaction_id, actor)

    # Aynı transaction'da exact replay yarışını serialize eder. Commit/rollback
    # burada yapılmaz; request-scoped get_db dependency'sine aittir.
    conn.execute("BEGIN IMMEDIATE")
    bundle = evidence_service.build_bundle(conn, transaction_id)
    snapshot_hash, snapshot, created = evidence_service.persist_snapshot(
        conn, transaction_id, bundle=bundle
    )

    if created:
        transaction_state = (snapshot.get("transaction") or {}).get("state") or "unknown"
        package = snapshot.get("ratification_package") or {}
        package_version = package.get("version", "none")
        audit.record(
            conn,
            audit.AuditActor(
                actor_type="user",
                user_id=actor.user_id,
                acting_entity_id=actor.acting_entity_id,
                request_id=actor.request_id,
            ),
            action="evidence_snapshot.created",
            target=f"evidence_snapshot:{snapshot_hash}",
            metadata_allowlist=frozenset(
                {"snapshot_hash", "package_version", "transaction_state"}
            ),
            metadata={
                "snapshot_hash": snapshot_hash,
                "package_version": package_version,
                "transaction_state": transaction_state,
            },
            transaction_id=transaction_id,
        )

    return _snapshot_response(snapshot_hash, snapshot, created=created)


@router.get("/{transaction_id}/evidence")
def get_legacy_evidence(
    transaction_id: str,
    token: str,
    response: Response,
    conn: Connection = Depends(get_db),
) -> dict:
    """Legacy capability bundle — read-only, deprecated, snapshot üretmez."""

    _require_legacy_capability_enabled(Settings.from_env())
    row = load_transaction(conn, transaction_id)
    if row is None:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı.")

    if resolve_party(row, token) is None and not resolve_manager(row, token):
        raise HTTPException(status_code=403, detail="Geçersiz token.")

    response.headers["Deprecation"] = "true"
    response.headers[
        "Link"
    ] = f'</api/transactions/{transaction_id}/evidence-bundle>; rel="replacement"'
    return evidence_service.build_bundle(
        conn, transaction_id, include_source_quote=True
    )
