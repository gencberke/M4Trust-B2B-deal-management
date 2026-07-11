"""FundingCoordinator v1 — yalnız package readiness ve funding_pending işareti.

Bu fazda PaymentGateway, Moka client veya legacy PaymentProvider çağrılmaz.
Gerçek pool funding Plan 06'da, funding-unit modeliyle uygulanacaktır.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from sqlite3 import Connection

from backend.app.eventbus import emit
from backend.app.services import audit
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from backend.app.services.account_lifecycle import (
    AccountLifecycleError,
    transition_account_state,
)
from backend.app.services.ratification_package import (
    PackageIntegrityError,
    RatificationPackageError,
    get_current,
    verify_integrity,
)


class FundingCoordinatorError(RatificationPackageError):
    """Funding readiness/coordinator domain hatası."""


@dataclass(frozen=True, slots=True)
class FundingResult:
    transaction_id: str
    package_id: str
    status: str
    event_emitted: bool


def _actor_for_audit(actor: ActorContext) -> audit.AuditActor:
    return audit.AuditActor(
        actor_type="user" if actor.user_id else "system",
        user_id=actor.user_id,
        acting_entity_id=actor.acting_entity_id,
        request_id=actor.request_id,
    )


def _schedule_summary(package) -> tuple[int, int]:
    payload = json.loads(package.canonical_payload_json)
    schedule = payload.get("funding_schedule") or {}
    milestones = schedule.get("milestones") or []
    unit_count = sum(len(milestone.get("funding_units") or []) for milestone in milestones)
    return unit_count, int(schedule.get("total_amount_minor") or 0)


def ensure_pool_funded(
    conn: Connection,
    transaction_id: str,
    package_id: str,
    actor_context: ActorContext,
) -> FundingResult:
    """Complete current package'ı provider çağırmadan funding_pending'e alır."""
    tx = conn.execute(
        "SELECT lifecycle_version, state FROM transactions WHERE id = ?",
        (transaction_id,),
    ).fetchone()
    if tx is None:
        raise FundingCoordinatorError("Transaction bulunamadı.")
    if tx["lifecycle_version"] != "account_v2":
        raise FundingCoordinatorError("Legacy transaction funding coordinator'a giremez.")

    package = get_current(conn, transaction_id)
    if package is None or package.id != package_id:
        raise FundingCoordinatorError("Package current/latest değil.")
    if package.status.value != "complete":
        raise FundingCoordinatorError("Package complete olmadan funding_pending üretilemez.")
    if not verify_integrity(package):
        raise PackageIntegrityError("Package canonical hash doğrulaması başarısız.")
    if review_service.has_blocking_case(conn, transaction_id, phase="pre_ratification"):
        raise FundingCoordinatorError("Blocking review case funding'i engelliyor.")

    if tx["state"] == "funding_pending":
        return FundingResult(transaction_id, package_id, "funding_pending", False)
    if tx["state"] in {"active", "settled", "cancelled", "rejected"}:
        raise FundingCoordinatorError("Transaction funding sonrası veya terminal durumda.")

    try:
        transition_account_state(
            conn,
            transaction_id=transaction_id,
            expected_states={"preparation", "awaiting_ratification", "awaiting_approval"},
            target_state="funding_pending",
            actor_context=actor_context,
            reason_code="RATIFICATION_COMPLETE",
        )
    except AccountLifecycleError as exc:
        raise FundingCoordinatorError(str(exc)) from exc

    unit_count, total_amount_minor = _schedule_summary(package)
    emit(
        conn,
        transaction_id,
        "funding_required",
        {
            "package_id": package_id,
            "funding_schedule_version": "funding_schedule_v1",
            "funding_unit_count": unit_count,
            "total_amount_minor": total_amount_minor,
        },
        "funding_coordinator",
    )
    audit.record(
        conn,
        _actor_for_audit(actor_context),
        action="funding.required",
        target=f"ratification_package:{package_id}",
        metadata_allowlist=frozenset({"package_id", "funding_unit_count"}),
        metadata={"package_id": package_id, "funding_unit_count": unit_count},
        transaction_id=transaction_id,
    )
    return FundingResult(transaction_id, package_id, "funding_pending", True)
