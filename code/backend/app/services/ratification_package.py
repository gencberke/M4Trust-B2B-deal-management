"""Canonical ratification package service (Plan 04 / Wave B / Faz 4D).

Bu servis yalnız account_v2 işlemler için document/rule/participant/policy ve
4C funding compiler çıktısını tek bir immutable canonical payload altında
bağlar. Ham doküman, extraction içeriği, token, secret ve serbest metin
package'a girmez. Service kendi transaction sınırını yönetmez.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from sqlite3 import Connection, Row
from uuid import uuid4

from backend.app.repositories import documents as documents_repo
from backend.app.repositories import packages as packages_repo
from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.repositories.transactions import load_transaction
from backend.app.schemas.payments import FundingScheduleSpec
from backend.app.schemas.ratification import RatificationPackage, RatificationPackageStatus
from backend.app.services import audit
from backend.app.services import participants as participants_service
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from backend.app.services.payments.domain import MOKA_STANDARD_PROFILE, ProviderCapabilities
from backend.app.services.payments.funding_plan import (
    FundingPlanDraft,
    compile_funding_plan,
    to_minor,
)
from backend.app.services.tracking_policy import load_tracking_policy

PACKAGE_SCHEMA_VERSION = "ratification_package_v1"
OTHER_TRX_CODE_DERIVATION_VERSION = "transaction_id_v1"
PROVIDER_PROFILE = "moka_standard_v1"


class RatificationPackageError(Exception):
    """Package domain hatalarının kökü."""


class PackageNotFoundError(RatificationPackageError):
    """Beklenen package bulunamadı."""


class PackageNotReadyError(RatificationPackageError):
    """Package için zorunlu readiness girdilerinden biri eksik."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


class PackageConflictError(RatificationPackageError):
    """Package amendment/state transition fail-closed conflict'i."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


class PackageIntegrityError(RatificationPackageError):
    """Canonical payload ile stored package hash eşleşmiyor."""


def canonical_package_json(payload: dict) -> str:
    """Canonical UTF-8 JSON string'i üretir; float payload'ı fail closed reddeder."""

    def reject_float(value: object) -> None:
        if isinstance(value, float):
            raise ValueError("Package payload float içeremez; para değerleri minor integer olmalı.")
        if isinstance(value, dict):
            for nested in value.values():
                reject_float(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                reject_float(nested)

    reject_float(payload)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def compute_package_hash(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_package(row: Row) -> RatificationPackage:
    return RatificationPackage(
        id=row["id"],
        transaction_id=row["transaction_id"],
        version=row["version"],
        document_id=row["document_id"],
        rule_set_version_id=row["rule_set_version_id"],
        tracking_policy_version_id=row["tracking_policy_version_id"],
        canonical_payload_json=row["canonical_payload_json"],
        document_hash=row["document_hash"],
        rule_set_hash=row["rule_set_hash"],
        participant_snapshot_hash=row["participant_snapshot_hash"],
        tracking_policy_hash=row["tracking_policy_hash"],
        package_hash=row["package_hash"],
        status=RatificationPackageStatus(row["status"]),
        created_at=row["created_at"],
        opened_at=row["opened_at"],
        completed_at=row["completed_at"],
    )


def _actor_for_audit(actor: ActorContext) -> audit.AuditActor:
    return audit.AuditActor(
        actor_type="user" if actor.user_id else "system",
        user_id=actor.user_id,
        acting_entity_id=actor.acting_entity_id,
        request_id=actor.request_id,
    )


def _require_account_transaction(conn: Connection, transaction_id: str) -> Row:
    row = load_transaction(conn, transaction_id)
    if row is None:
        raise PackageNotFoundError("Transaction bulunamadı.")
    if row["lifecycle_version"] != "account_v2":
        raise PackageConflictError(
            "LEGACY_TRANSACTION",
            "Ratification package yalnız account_v2 işlemler için oluşturulabilir.",
        )
    return row


def _assert_pre_funding_state(row: Row) -> None:
    if row["state"] in {"funding_pending", "active", "settled", "cancelled", "rejected"}:
        raise PackageConflictError(
            "PACKAGE_AMENDMENT_LOCKED",
            "Funding sonrası veya terminal durumdaki işlemde package değiştirilemez.",
        )


def _capabilities_payload(capabilities: ProviderCapabilities) -> dict[str, bool]:
    return {
        "supports_pool_payment": capabilities.supports_pool_payment,
        "supports_partial_pool_approval": capabilities.supports_partial_pool_approval,
        "supports_multiple_approvals_per_payment": capabilities.supports_multiple_approvals_per_payment,
        "supports_approval_undo": capabilities.supports_approval_undo,
        "supports_fixed_tranches": capabilities.supports_fixed_tranches,
        "supports_marketplace_subdealers": capabilities.supports_marketplace_subdealers,
    }


def _decimal_string(value: float) -> str:
    decimal = Decimal(str(value)).normalize()
    return format(decimal, "f")


def _funding_plan_payload(plan: FundingPlanDraft) -> dict:
    return {
        "currency": plan.currency,
        "total_amount_minor": plan.total_amount_minor,
        "milestones": [
            {
                "rule_index": milestone.rule_index,
                "title": milestone.title,
                "trigger_type": milestone.trigger_type,
                "basis_points": milestone.basis_points,
                "amount_minor": milestone.amount_minor,
                "currency": milestone.currency,
                "required_evidence": list(milestone.required_evidence),
                "release_mode": milestone.release_mode.value,
                "funding_units": [
                    {
                        "sequence": unit.sequence,
                        "amount_minor": unit.amount_minor,
                        "eligibility_type": unit.eligibility_type,
                        "eligibility_payload": dict(unit.eligibility_payload),
                    }
                    for unit in milestone.funding_units
                ],
            }
            for milestone in plan.milestones
        ],
    }


@dataclass(frozen=True, slots=True)
class _PackageInputs:
    document_id: str
    document_hash: str
    rule_set_version_id: str
    rule_set_hash: str
    participant_snapshot_hash: str
    tracking_policy_hash: str
    canonical_payload_json: str
    package_hash: str
    tracking_policy_version_id: str | None = None


def _build_inputs(
    conn: Connection,
    *,
    transaction_id: str,
    funding_schedule_spec: FundingScheduleSpec,
    capabilities: ProviderCapabilities,
) -> _PackageInputs:
    transaction = _require_account_transaction(conn, transaction_id)
    _assert_pre_funding_state(transaction)

    document = documents_repo.get_current_active(conn, transaction_id)
    if document is None:
        raise PackageNotReadyError("DOCUMENT_NOT_READY", "Aktif contract document bulunamadı.")

    current_rule = rule_sets_repo.get_current(conn, transaction_id)
    if (
        current_rule is None
        or current_rule.rule_set_id is None
        or current_rule.extraction is None
    ):
        raise PackageNotReadyError("RULE_SET_NOT_READY", "Current rule-set bulunamadı.")
    if current_rule.validator_status != "PASS" or current_rule.status != "ratifiable":
        raise PackageNotReadyError(
            "RULE_SET_NOT_RATIFIABLE",
            "Current rule-set PASS ve ratifiable olmalıdır.",
        )

    participants = {
        participant.role.value: participant
        for participant in participants_service.list_participants(conn, transaction_id)
    }
    buyer = participants.get("buyer")
    seller = participants.get("seller")
    if buyer is None or seller is None or buyer.confirmed_snapshot is None or seller.confirmed_snapshot is None:
        raise PackageNotReadyError(
            "PARTICIPANTS_NOT_CONFIRMED",
            "Buyer ve seller confirmed snapshot sahibi olmalıdır.",
        )
    if buyer.legal_entity_id is None or seller.legal_entity_id is None:
        raise PackageNotReadyError(
            "PARTICIPANTS_NOT_BOUND",
            "Buyer ve seller legal entity ile bağlı olmalıdır.",
        )
    if buyer.legal_entity_id == seller.legal_entity_id:
        raise PackageConflictError(
            "SAME_LEGAL_ENTITY",
            "Buyer ve seller farklı legal entity olmalıdır.",
        )

    participant_snapshot = {
        "buyer": buyer.confirmed_snapshot.model_dump(mode="json"),
        "seller": seller.confirmed_snapshot.model_dump(mode="json"),
    }
    participant_snapshot_hash = compute_package_hash(canonical_package_json(participant_snapshot))

    policy = load_tracking_policy(conn, transaction_id)
    if policy is None or policy.status.value != "locked":
        raise PackageNotReadyError(
            "TRACKING_POLICY_NOT_LOCKED",
            "Takip policy package öncesinde locked olmalıdır.",
        )
    policy_payload = policy.model_dump(mode="json")
    tracking_policy_hash = compute_package_hash(canonical_package_json(policy_payload))

    if review_service.has_blocking_case(conn, transaction_id, phase="pre_ratification"):
        raise PackageNotReadyError(
            "BLOCKING_REVIEW",
            "Blocking pre-ratification review case package oluşturmayı engeller.",
        )

    extraction = current_rule.extraction
    currency = extraction.commercial_terms.currency.value
    total_amount_minor = to_minor(extraction.commercial_terms.total_amount, currency)
    funding_plan = compile_funding_plan(
        extraction.payment_rules,
        total_amount_minor,
        currency,
        funding_schedule_spec,
        capabilities,
    )
    commercial_summary = {
        "currency": currency,
        "total_amount_minor": total_amount_minor,
        "delivery_deadline": extraction.commercial_terms.delivery_deadline,
        "goods": [
            {
                "name": goods.name,
                "quantity": _decimal_string(goods.quantity),
                "unit": goods.unit,
            }
            for goods in extraction.commercial_terms.goods
        ],
    }
    canonical_payload = {
        "package_schema_version": PACKAGE_SCHEMA_VERSION,
        "document": {"id": document["id"], "content_sha256": document["content_sha256"]},
        "rule_set": {
            "id": current_rule.rule_set_id,
            "version": current_rule.version,
            "rules_hash": current_rule.rules_hash,
        },
        "participant_snapshot_hash": participant_snapshot_hash,
        "tracking_policy": {
            "version_id": None,
            "snapshot": policy_payload,
            "hash": tracking_policy_hash,
        },
        "funding_schedule": _funding_plan_payload(funding_plan),
        "funding_schedule_spec": funding_schedule_spec.model_dump(mode="json"),
        "commercial_summary": commercial_summary,
        "provider_profile": PROVIDER_PROFILE,
        "provider_capabilities": _capabilities_payload(capabilities),
        "other_trx_code_derivation_version": OTHER_TRX_CODE_DERIVATION_VERSION,
        "schema_version": PACKAGE_SCHEMA_VERSION,
    }
    canonical = canonical_package_json(canonical_payload)
    return _PackageInputs(
        document_id=document["id"],
        document_hash=document["content_sha256"],
        rule_set_version_id=current_rule.rule_set_id,
        rule_set_hash=current_rule.rules_hash or "",
        participant_snapshot_hash=participant_snapshot_hash,
        tracking_policy_hash=tracking_policy_hash,
        canonical_payload_json=canonical,
        package_hash=compute_package_hash(canonical),
    )


def _same_inputs(package: RatificationPackage, inputs: _PackageInputs) -> bool:
    return (
        package.document_id == inputs.document_id
        and package.document_hash == inputs.document_hash
        and package.rule_set_version_id == inputs.rule_set_version_id
        and package.rule_set_hash == inputs.rule_set_hash
        and package.participant_snapshot_hash == inputs.participant_snapshot_hash
        and package.tracking_policy_hash == inputs.tracking_policy_hash
        and package.canonical_payload_json == inputs.canonical_payload_json
        and package.package_hash == inputs.package_hash
    )


def _insert_package(
    conn: Connection, *, transaction_id: str, inputs: _PackageInputs
) -> RatificationPackage:
    package_id = uuid4().hex
    packages_repo.insert_package(
        conn,
        package_id=package_id,
        transaction_id=transaction_id,
        version=packages_repo.get_max_version(conn, transaction_id) + 1,
        document_id=inputs.document_id,
        rule_set_version_id=inputs.rule_set_version_id,
        tracking_policy_version_id=inputs.tracking_policy_version_id,
        canonical_payload_json=inputs.canonical_payload_json,
        document_hash=inputs.document_hash,
        rule_set_hash=inputs.rule_set_hash,
        participant_snapshot_hash=inputs.participant_snapshot_hash,
        tracking_policy_hash=inputs.tracking_policy_hash,
        package_hash=inputs.package_hash,
        status=RatificationPackageStatus.draft.value,
        created_at=_utc_now_iso(),
    )
    return _row_to_package(packages_repo.get_by_id(conn, package_id))


def build_current_package(
    conn: Connection,
    *,
    transaction_id: str,
    funding_schedule_spec: FundingScheduleSpec,
    capabilities: ProviderCapabilities,
    actor_context: ActorContext,
) -> RatificationPackage:
    """Readiness tamam ise current package'ı idempotent üretir veya döndürür."""
    del actor_context
    inputs = _build_inputs(
        conn,
        transaction_id=transaction_id,
        funding_schedule_spec=funding_schedule_spec,
        capabilities=capabilities,
    )
    current_row = packages_repo.get_current(conn, transaction_id)
    if current_row is not None:
        current = _row_to_package(current_row)
        if _same_inputs(current, inputs):
            return current
        raise PackageConflictError(
            "PACKAGE_INPUTS_CHANGED",
            "Package girdileri değişti; supersede_if_inputs_changed çağrılmalıdır.",
        )
    return _insert_package(conn, transaction_id=transaction_id, inputs=inputs)


def open_package(
    conn: Connection,
    *,
    package_id: str,
    actor_context: ActorContext,
) -> RatificationPackage:
    """Current draft package'ı ratification için open duruma taşır."""
    row = packages_repo.get_by_id(conn, package_id)
    if row is None:
        raise PackageNotFoundError(package_id)
    transaction = _require_account_transaction(conn, row["transaction_id"])
    _assert_pre_funding_state(transaction)
    current = packages_repo.get_current(conn, row["transaction_id"])
    if current is None or current["id"] != package_id:
        raise PackageConflictError("STALE_PACKAGE", "Yalnız current package open edilebilir.")
    package = _row_to_package(row)
    if not verify_integrity(package):
        raise PackageIntegrityError("Package canonical hash doğrulaması başarısız.")
    if package.status is RatificationPackageStatus.draft:
        packages_repo.update_opened(
            conn, package_id=package_id, opened_at=_utc_now_iso()
        )
        audit.record(
            conn,
            _actor_for_audit(actor_context),
            action="ratification_package.opened",
            target=f"ratification_package:{package_id}",
            metadata_allowlist=frozenset({"package_version"}),
            metadata={"package_version": package.version},
            transaction_id=package.transaction_id,
        )
    return _row_to_package(packages_repo.get_by_id(conn, package_id))


def supersede_if_inputs_changed(
    conn: Connection,
    *,
    transaction_id: str,
    funding_schedule_spec: FundingScheduleSpec,
    capabilities: ProviderCapabilities,
    actor_context: ActorContext,
) -> RatificationPackage:
    """Input değişiminde eski current package'ı supersede edip yeni version üretir."""
    inputs = _build_inputs(
        conn,
        transaction_id=transaction_id,
        funding_schedule_spec=funding_schedule_spec,
        capabilities=capabilities,
    )
    current_row = packages_repo.get_current(conn, transaction_id)
    if current_row is None:
        return _insert_package(conn, transaction_id=transaction_id, inputs=inputs)
    current = _row_to_package(current_row)
    if _same_inputs(current, inputs):
        return current

    packages_repo.mark_superseded(conn, current.id)
    audit.record(
        conn,
        _actor_for_audit(actor_context),
        action="ratification_package.superseded",
        target=f"ratification_package:{current.id}",
        metadata_allowlist=frozenset({"reason_code"}),
        metadata={"reason_code": "INPUTS_CHANGED"},
        transaction_id=transaction_id,
    )
    return _insert_package(conn, transaction_id=transaction_id, inputs=inputs)


def get_current(conn: Connection, transaction_id: str) -> RatificationPackage | None:
    row = packages_repo.get_current(conn, transaction_id)
    return None if row is None else _row_to_package(row)


def verify_integrity(package: RatificationPackage) -> bool:
    return compute_package_hash(package.canonical_payload_json) == package.package_hash
