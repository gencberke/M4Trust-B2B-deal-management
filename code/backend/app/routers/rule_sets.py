"""Account v2 rule revision/revalidation uçları (Plan 04 / Faz 4F-1).

Revision isteği JSON Patch değildir: body tam `ExtractionJSON` payload'ıdır.
Router yalnız creator-side manager yetkisi, lifecycle/pre-ratification kapısı
ve transaction orchestration'ını yürütür; immutable version üretimi ve
deterministic validation donmuş `RuleVersionService`'e aittir.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from backend.app.api.errors import ApiError
from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.eventbus import emit
from backend.app.repositories import participants as participants_repo
from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.repositories.transactions import load_transaction
from backend.app.schemas.rule_revisions import ExtractionRevisionRequest
from backend.app.schemas.payments import FundingScheduleSpec
from backend.app.schemas.rule_sets import (
    RuleSetVersion,
    RuleSetVersionHistoryPublicView,
    RuleSetVersionPublicView,
)
from backend.app.services import audit
from backend.app.services import ratification_package as package_service
from backend.app.services import review as review_service
from backend.app.services import rule_versions
from backend.app.services import participants as participants_service
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.auth import require_csrf_protection
from backend.app.services.extraction_projection import redacted_extraction_projection
from backend.app.services.payments.domain import MOKA_STANDARD_PROFILE

router = APIRouter(tags=["rule-sets"])

_PRE_RATIFICATION_STATES = frozenset(
    {"preparation", "awaiting_review", "awaiting_approval", "awaiting_ratification"}
)
_POST_RATIFICATION_STATES = frozenset(
    {"funding_pending", "active", "settled", "cancelled", "rejected"}
)


def _require_creator_manager(
    conn: sqlite3.Connection, transaction_id: str, actor: ActorContext, transaction
) -> None:
    owner_entity_id = transaction["owner_entity_id"]
    assignment = (
        participants_repo.get_active_assignment(
            conn, transaction_id, actor.user_id or "", role="manager"
        )
        if actor.user_id is not None
        else None
    )
    if (
        owner_entity_id is None
        or actor.acting_entity_id != owner_entity_id
        or assignment is None
        or assignment["legal_entity_id"] != owner_entity_id
    ):
        raise ApiError(
            status_code=403,
            code="RULE_REVISION_FORBIDDEN",
            message="Yalnız creator-side manager kural revizyonu yapabilir.",
        )


def _load_revision_context(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    version_id: str,
    actor: ActorContext,
) -> tuple[sqlite3.Row, sqlite3.Row]:
    transaction = load_transaction(conn, transaction_id)
    if transaction is None:
        raise ApiError(status_code=404, code="TRANSACTION_NOT_FOUND", message="İşlem bulunamadı.")
    if transaction["lifecycle_version"] != "account_v2":
        raise ApiError(
            status_code=409,
            code="LEGACY_RULE_REVISION_FORBIDDEN",
            message="Rule revision yalnız account_v2 işlemler için kullanılabilir.",
        )
    if transaction["state"] in _POST_RATIFICATION_STATES:
        raise ApiError(
            status_code=409,
            code="RULE_REVISION_AFTER_RATIFICATION",
            message="Ratification/funding sonrası rule revision yapılamaz.",
        )
    if transaction["state"] not in _PRE_RATIFICATION_STATES:
        raise ApiError(
            status_code=409,
            code="RULE_REVISION_NOT_ALLOWED",
            message="İşlem pre-ratification durumunda değil.",
        )

    _require_creator_manager(conn, transaction_id, actor, transaction)

    parent = rule_sets_repo.get_by_id(conn, version_id)
    if parent is None or parent["transaction_id"] != transaction_id:
        raise ApiError(status_code=404, code="RULE_SET_NOT_FOUND", message="Rule-set bulunamadı.")
    current = rule_sets_repo.get_latest_non_superseded(conn, transaction_id)
    if current is None or current["id"] != version_id:
        raise ApiError(
            status_code=409,
            code="STALE_RULE_SET_VERSION",
            message="Revision parent version artık current değil.",
        )
    return transaction, parent


def _safe_findings(version: RuleSetVersion) -> list[dict[str, str]]:
    """Validator raporundan yalnız deterministic code/severity alanlarını seçer."""
    safe: list[dict[str, str]] = []
    for finding in version.validator_report or []:
        if not isinstance(finding, dict):
            continue
        code = finding.get("code")
        severity = finding.get("severity")
        if isinstance(code, str) and isinstance(severity, str):
            safe.append({"code": code, "severity": severity})
    return safe


def _to_public_view(version: RuleSetVersion) -> RuleSetVersionPublicView:
    extraction = redacted_extraction_projection(
        version.extraction.model_dump(mode="json"), include_source_quote=False
    )
    assert extraction is not None
    return RuleSetVersionPublicView(
        id=version.id,
        transaction_id=version.transaction_id,
        version=version.version,
        parent_version_id=version.parent_version_id,
        extraction=extraction,
        rules_hash=version.rules_hash,
        validator_status=version.validator_status,
        validator_report=_safe_findings(version) or None,
        status=version.status,
        created_by_user_id=version.created_by_user_id,
        created_at=version.created_at,
    )


def _schedule_spec_from_package(package) -> FundingScheduleSpec:
    try:
        payload = json.loads(package.canonical_payload_json)
        return FundingScheduleSpec.model_validate(payload.get("funding_schedule_spec") or {})
    except (TypeError, ValueError, ValidationError) as exc:
        raise ApiError(
            status_code=409,
            code="PACKAGE_INPUTS_INVALID",
            message="Current package funding schedule girdisi doğrulanamadı.",
        ) from exc


def _sync_package_after_validation(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    validator_status: str | None,
    actor: ActorContext,
) -> None:
    """Rule input değişince mevcut package'ı fail-closed biçimde günceller."""
    current_package = package_service.get_current(conn, transaction_id)
    if current_package is None:
        return

    if validator_status != "PASS":
        package_service._supersede_current_for_rule_revision(  # noqa: SLF001 — dar internal seam
            conn, transaction_id=transaction_id, actor_context=actor
        )
        return

    schedule_spec = _schedule_spec_from_package(current_package)
    try:
        package_service.supersede_if_inputs_changed(
            conn,
            transaction_id=transaction_id,
            funding_schedule_spec=schedule_spec,
            capabilities=MOKA_STANDARD_PROFILE,
            actor_context=actor,
        )
    except package_service.PackageNotReadyError:
        # PASS tek başına blocking review'u bypass edemez; eski package da
        # ratify edilemez. Review çözülene kadar current package yoktur.
        package_service._supersede_current_for_rule_revision(  # noqa: SLF001
            conn, transaction_id=transaction_id, actor_context=actor
        )
    except package_service.PackageIntegrityError as exc:
        raise ApiError(
            status_code=409,
            code="PACKAGE_INTEGRITY_FAILED",
            message="Current package bütünlük doğrulamasından geçmedi.",
        ) from exc
    except package_service.PackageConflictError as exc:
        raise ApiError(status_code=409, code=exc.reason_code, message=str(exc)) from exc


def _record_revision_side_effects(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    parent: sqlite3.Row,
    version: RuleSetVersion,
    actor: ActorContext,
) -> None:
    findings = _safe_findings(version)
    finding_codes = [finding["code"] for finding in findings]
    emit(
        conn,
        transaction_id,
        "rule_set_revised",
        {
            "parent_version_id": parent["id"],
            "rule_set_version_id": version.id,
            "version": version.version,
            "validator_status": version.validator_status,
            "finding_codes": finding_codes,
        },
        "rule_revision",
    )
    emit(
        conn,
        transaction_id,
        "rules_validated",
        {
            "status": version.validator_status,
            "rule_set_version_id": version.id,
            "finding_codes": finding_codes,
        },
        "validator",
    )
    audit.record(
        conn,
        audit.AuditActor(
            actor_type="user",
            user_id=actor.user_id,
            acting_entity_id=actor.acting_entity_id,
            request_id=actor.request_id,
        ),
        action="rule_set.revised",
        target=f"rule_set_version:{version.id}",
        metadata_allowlist=frozenset(
            {"parent_version_id", "version", "validator_status", "finding_count"}
        ),
        metadata={
            "parent_version_id": parent["id"],
            "version": version.version,
            "validator_status": version.validator_status or "UNKNOWN",
            "finding_count": len(finding_codes),
        },
        transaction_id=transaction_id,
    )


def _record_validation_audit(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    version: RuleSetVersion,
    actor: ActorContext,
) -> None:
    audit.record(
        conn,
        audit.AuditActor(
            actor_type="user",
            user_id=actor.user_id,
            acting_entity_id=actor.acting_entity_id,
            request_id=actor.request_id,
        ),
        action="rule_set.validated",
        target=f"rule_set_version:{version.id}",
        metadata_allowlist=frozenset({"version", "validator_status", "finding_count"}),
        metadata={
            "version": version.version,
            "validator_status": version.validator_status or "UNKNOWN",
            "finding_count": len(_safe_findings(version)),
        },
        transaction_id=transaction_id,
    )


def _open_review_if_needed(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    version: RuleSetVersion,
    actor: ActorContext,
) -> None:
    if version.validator_status != "NEEDS_REVIEW":
        return
    review_service.open_validator_case(
        conn,
        transaction_id=transaction_id,
        source_id=version.id,
        validator_status=version.validator_status,
        finding_codes=[finding["code"] for finding in _safe_findings(version)],
        actor_context=actor,
    )


def _revision(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    version_id: str,
    payload: ExtractionRevisionRequest,
    actor: ActorContext,
) -> RuleSetVersion:
    _transaction, parent = _load_revision_context(
        conn,
        transaction_id=transaction_id,
        version_id=version_id,
        actor=actor,
    )

    # A conditional status update reserves the current parent before the new
    # row is inserted. A concurrent request therefore fails stale/UNIQUE and
    # the caller's DB dependency rolls the whole mutation back.
    if not rule_sets_repo.mark_superseded_if_current(
        conn, transaction_id=transaction_id, version_id=version_id
    ):
        raise ApiError(
            status_code=409,
            code="STALE_RULE_SET_VERSION",
            message="Revision parent version artık current değil.",
        )

    try:
        revision = rule_versions.create_revision(
            conn,
            transaction_id=transaction_id,
            parent_version_id=version_id,
            rules_payload=payload.model_dump(mode="json"),
            actor_context=actor,
        )
    except rule_versions.RuleRevisionPayloadError as exc:
        raise ApiError(
            status_code=422,
            code="RULE_REVISION_SOURCE_QUOTE_REQUIRED",
            message="Omitted source_quote parent rule index'inden yeniden kurulamadÄ±.",
        ) from exc
    except sqlite3.IntegrityError as exc:
        raise ApiError(
            status_code=409,
            code="RULE_REVISION_CONFLICT",
            message="Rule revision eşzamanlı bir değişiklik nedeniyle oluşturulamadı.",
        ) from exc

    validated = rule_versions.validate_version(
        conn,
        version_id=revision.id,
        confidence_threshold=Settings.from_env().validator_confidence_threshold,
    )
    _open_review_if_needed(
        conn, transaction_id=transaction_id, version=validated, actor=actor
    )
    _sync_package_after_validation(
        conn,
        transaction_id=transaction_id,
        validator_status=validated.validator_status,
        actor=actor,
    )
    _record_revision_side_effects(
        conn,
        transaction_id=transaction_id,
        parent=parent,
        version=validated,
        actor=actor,
    )
    return validated


@router.get(
    "/api/transactions/{transaction_id}/rule-sets",
    response_model=RuleSetVersionHistoryPublicView,
)
def list_rule_set_versions(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: sqlite3.Connection = Depends(get_db),
) -> RuleSetVersionHistoryPublicView:
    """Assignment-scoped current rule and immutable version history."""

    transaction = load_transaction(conn, transaction_id)
    if transaction is None:
        raise ApiError(status_code=404, code="TRANSACTION_NOT_FOUND", message="Ä°ÅŸlem bulunamadÄ±.")
    if transaction["lifecycle_version"] != "account_v2":
        raise ApiError(
            status_code=409,
            code="LEGACY_RULE_SET_READ_FORBIDDEN",
            message="Rule-set version history yalnÄ±z account_v2 iÅŸlemler iÃ§in kullanÄ±labilir.",
        )
    if actor.user_id is None or not participants_service.has_transaction_access(
        conn, transaction_id, actor.user_id
    ):
        raise ApiError(
            status_code=403,
            code="TRANSACTION_ACCESS_DENIED",
            message="Bu iÅŸlemde eriÅŸiminiz yok.",
        )

    versions = rule_versions.list_versions(conn, transaction_id)
    current_row = rule_sets_repo.get_latest_non_superseded(conn, transaction_id)
    public_versions = [_to_public_view(version) for version in versions]
    current_version = next(
        (version for version in public_versions if current_row and version.id == current_row["id"]),
        None,
    )
    return RuleSetVersionHistoryPublicView(
        transaction_id=transaction_id,
        current_version_id=current_row["id"] if current_row is not None else None,
        current_version=current_version,
        versions=public_versions,
    )


@router.post(
    "/api/transactions/{transaction_id}/rule-sets/{version_id}/revisions",
    response_model=RuleSetVersionPublicView,
)
def create_rule_set_revision(
    transaction_id: str,
    version_id: str,
    payload: ExtractionRevisionRequest,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: sqlite3.Connection = Depends(get_db),
) -> RuleSetVersionPublicView:
    return _to_public_view(
        _revision(
            conn,
            transaction_id=transaction_id,
            version_id=version_id,
            payload=payload,
            actor=actor,
        )
    )


@router.post(
    "/api/transactions/{transaction_id}/rule-sets/{version_id}/validate",
    response_model=RuleSetVersionPublicView,
)
def validate_rule_set_version(
    transaction_id: str,
    version_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: sqlite3.Connection = Depends(get_db),
) -> RuleSetVersionPublicView:
    _transaction, _parent = _load_revision_context(
        conn,
        transaction_id=transaction_id,
        version_id=version_id,
        actor=actor,
    )
    try:
        validated = rule_versions.validate_version(
            conn,
            version_id=version_id,
            confidence_threshold=Settings.from_env().validator_confidence_threshold,
        )
    except rule_versions.RuleSetVersionNotFoundError as exc:
        raise ApiError(status_code=404, code="RULE_SET_NOT_FOUND", message="Rule-set bulunamadı.") from exc

    _open_review_if_needed(
        conn, transaction_id=transaction_id, version=validated, actor=actor
    )
    _sync_package_after_validation(
        conn,
        transaction_id=transaction_id,
        validator_status=validated.validator_status,
        actor=actor,
    )
    emit(
        conn,
        transaction_id,
        "rules_validated",
        {
            "status": validated.validator_status,
            "rule_set_version_id": validated.id,
            "finding_codes": [finding["code"] for finding in _safe_findings(validated)],
        },
        "validator",
    )
    _record_validation_audit(
        conn, transaction_id=transaction_id, version=validated, actor=actor
    )
    return _to_public_view(validated)
