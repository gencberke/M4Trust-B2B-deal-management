"""Account ratification service (Plan 04 / Wave B / Faz 4E, v2 §7.3, §8.5).

Yalnız participant approver kendi participant/entity adına ratification
verir; ikinci geçerli ratification package'ı `complete` yapar ve ardından
YALNIZ `FundingCoordinator.ensure_pool_funded` çağrılır — bu servis provider
çağırmaz (v2 §8.5, Moka §18.2). Kendi connection'ını açmaz, commit/rollback
yapmaz; business mutation + audit çağıranın transaction'ının parçasıdır.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from sqlite3 import Connection, Row
from uuid import uuid4

from backend.app.repositories import packages as packages_repo
from backend.app.repositories import ratifications as ratifications_repo
from backend.app.schemas.ratification import (
    Ratification,
    RatificationOutcome,
    RatificationPackage,
    RatificationPackageStatus,
)
from backend.app.services import audit
from backend.app.services import participants as participants_service
from backend.app.services.access_control import ActorContext
from backend.app.services.payments.funding_coordinator import ensure_pool_funded
from backend.app.services.ratification_package import verify_integrity

_REQUIRED_ROLES = frozenset({"buyer", "seller"})


class RatificationError(Exception):
    """Ratification domain hatalarının kökü."""


class RatificationPackageNotFoundError(RatificationError):
    """Belirtilen package bulunamadı."""


class RatificationAuthorizationError(RatificationError):
    """Actor bu package için ratification vermeye yetkili değil."""


class RatificationConflictError(RatificationError):
    """Package durumu ratification'a uygun değil (fail closed)."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


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


def _row_to_ratification(row: Row) -> Ratification:
    return Ratification(
        id=row["id"],
        package_id=row["package_id"],
        transaction_id=row["transaction_id"],
        participant_id=row["participant_id"],
        user_id=row["user_id"],
        legal_entity_id=row["legal_entity_id"],
        participant_role=row["participant_role"],
        auth_method=row["auth_method"],
        approved_at=row["approved_at"],
        client_ip_hash=row["client_ip_hash"],
        user_agent_summary=row["user_agent_summary"],
    )


def _actor_for_audit(actor: ActorContext) -> audit.AuditActor:
    return audit.AuditActor(
        actor_type="user" if actor.user_id else "system",
        user_id=actor.user_id,
        acting_entity_id=actor.acting_entity_id,
        request_id=actor.request_id,
    )


def get_package_or_raise(conn: Connection, package_id: str) -> RatificationPackage:
    row = packages_repo.get_by_id(conn, package_id)
    if row is None:
        raise RatificationPackageNotFoundError(package_id)
    return _row_to_package(row)


_TERMINAL_STATUS_REASONS = {
    RatificationPackageStatus.draft: "PACKAGE_NOT_OPEN",
    RatificationPackageStatus.superseded: "PACKAGE_SUPERSEDED",
    RatificationPackageStatus.cancelled: "PACKAGE_CANCELLED",
}


def _reject_if_terminal(package: RatificationPackage) -> None:
    """`draft`/`superseded`/`cancelled` her zaman reddedilir -- idempotency

    kontrolünden ÖNCE çağrılır. Aksi halde: taraf package'ı ratify eder, sonra
    package rule/policy değişimiyle supersede edilir, taraf AYNI eski
    package'a tekrar istek atar -- mevcut ratification satırı bulunduğu için
    idempotency kapısı bunu 409 yerine yanlışlıkla 200 olarak geçirirdi.
    """
    reason_code = _TERMINAL_STATUS_REASONS.get(package.status)
    if reason_code is not None:
        raise RatificationConflictError(
            reason_code, f"Package '{package.status.value}' durumunda ratify edilemez."
        )


def create_ratification(
    conn: Connection,
    *,
    package_id: str,
    actor_context: ActorContext,
    auth_method: str,
    client_ip_hash: str | None = None,
    user_agent_summary: str | None = None,
) -> RatificationOutcome:
    """Actor'ın KENDİ participant/entity'si adına package'ı ratify eder.

    Aynı (package, participant) çifti için idempotenttir. Aynı user farklı bir
    participant adına (iki taraf) ratification veremez. İkinci geçerli
    ratification package'ı `complete` yapar ve provider çağırmadan yalnız
    `FundingCoordinator.ensure_pool_funded`'ı tetikler.
    """
    if actor_context.user_id is None:
        raise RatificationAuthorizationError("Ratification authenticated user gerektirir.")

    package = get_package_or_raise(conn, package_id)

    my_participant = participants_service.get_my_participant_for_actor(
        conn, package.transaction_id, actor_context
    )
    if my_participant is None or my_participant.legal_entity_id is None:
        raise RatificationAuthorizationError(
            "Actor bu işlemde bağlı bir participant değil."
        )
    if my_participant.role.value not in _REQUIRED_ROLES:
        raise RatificationAuthorizationError("Yalnız buyer/seller ratification verebilir.")

    _reject_if_terminal(package)

    existing = ratifications_repo.get_by_package_and_participant(
        conn, package_id=package_id, participant_id=my_participant.id
    )
    if existing is not None:
        return _build_outcome(conn, package, _row_to_ratification(existing), funding_triggered=False)

    if package.status is RatificationPackageStatus.complete:
        raise RatificationConflictError(
            "PACKAGE_ALREADY_COMPLETE", "Package zaten complete durumunda; yeni ratification kabul edilmez."
        )
    if not verify_integrity(package):
        raise RatificationConflictError(
            "PACKAGE_INTEGRITY_FAILED", "Package canonical hash doğrulaması başarısız."
        )

    same_user_other_side = ratifications_repo.get_by_package_and_user(
        conn, package_id=package_id, user_id=actor_context.user_id
    )
    if same_user_other_side is not None:
        raise RatificationAuthorizationError(
            "Aynı user aynı package'ta iki taraf adına ratification veremez."
        )

    ratification_id = uuid4().hex
    approved_at = _utc_now_iso()
    try:
        ratifications_repo.insert(
            conn,
            id=ratification_id,
            package_id=package_id,
            transaction_id=package.transaction_id,
            participant_id=my_participant.id,
            user_id=actor_context.user_id,
            legal_entity_id=my_participant.legal_entity_id,
            participant_role=my_participant.role.value,
            auth_method=auth_method,
            approved_at=approved_at,
            client_ip_hash=client_ip_hash,
            user_agent_summary=user_agent_summary,
        )
    except sqlite3.IntegrityError:
        # UNIQUE(package_id, participant_id) yarışı: source of truth DB'dir --
        # eşzamanlı ikinci istek idempotent olarak mevcut satırı döner.
        existing = ratifications_repo.get_by_package_and_participant(
            conn, package_id=package_id, participant_id=my_participant.id
        )
        if existing is None:
            raise
        return _build_outcome(conn, package, _row_to_ratification(existing), funding_triggered=False)

    audit.record(
        conn,
        _actor_for_audit(actor_context),
        action="ratification.submitted",
        target=f"ratification_package:{package_id}",
        # not: metadata key "participant_role" DEĞİL -- "pan" (kart numarası)
        # forbidden-key marker'ı "particiPANt" alt string'ini yanlış yakalar.
        metadata_allowlist=frozenset({"role"}),
        metadata={"role": my_participant.role.value},
        transaction_id=package.transaction_id,
    )

    roles = ratifications_repo.distinct_roles_for_package(conn, package_id)
    funding_triggered = False
    package_status = package.status
    if _REQUIRED_ROLES <= roles:
        packages_repo.mark_complete(conn, package_id=package_id, completed_at=_utc_now_iso())
        package_status = RatificationPackageStatus.complete
        ensure_pool_funded(conn, package.transaction_id, package_id, actor_context)
        funding_triggered = True

    ratification_row = ratifications_repo.get_by_package_and_participant(
        conn, package_id=package_id, participant_id=my_participant.id
    )
    return RatificationOutcome(
        ratification=_row_to_ratification(ratification_row),
        package_status=package_status,
        funding_triggered=funding_triggered,
    )


def _build_outcome(
    conn: Connection,
    package: RatificationPackage,
    ratification: Ratification,
    *,
    funding_triggered: bool,
) -> RatificationOutcome:
    current = packages_repo.get_by_id(conn, package.id)
    status = RatificationPackageStatus(current["status"]) if current is not None else package.status
    return RatificationOutcome(
        ratification=ratification, package_status=status, funding_triggered=funding_triggered
    )


def list_ratifications(conn: Connection, package_id: str) -> list[Ratification]:
    return [_row_to_ratification(row) for row in ratifications_repo.list_by_package(conn, package_id)]
