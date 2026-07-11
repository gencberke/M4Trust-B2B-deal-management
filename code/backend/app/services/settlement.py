"""Kilitli policy ve kanıtlardan deterministik ödeme mutabakatını yürütür."""

from __future__ import annotations

from sqlite3 import Connection

from backend.app.config import Settings
from backend.app.eventbus import emit
from backend.app.repositories import disputes as disputes_repo
from backend.app.repositories import evidence as evidence_repo
from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.schemas.extraction import ExtractionJSON
from backend.app.services.decision import DecisionResult, decide
from backend.app.services.effective_requirements import resolve_effective_requirements
from backend.app.services import evidence_records as evidence_records_service
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from backend.app.services.payment_provider import make_payment_provider
from backend.app.services.tracking_policy import load_tracking_policy

_LEGACY_FUNDED_STATES = {"active", "evidence_pending"}


def _load_extraction(conn: Connection, transaction_id: str) -> ExtractionJSON | None:
    """Merkezi current-rule okuma kapısı üzerinden (§11) — account/legacy ayrımını bilmez."""
    current = rule_sets_repo.get_current(conn, transaction_id)
    return None if current is None else current.extraction


def _has_both_approvals(conn: Connection, transaction_id: str) -> bool:
    parties = {
        row["party"]
        for row in conn.execute(
            "SELECT DISTINCT party FROM approvals WHERE transaction_id = ?",
            (transaction_id,),
        ).fetchall()
    }
    return {"buyer", "seller"} <= parties


def _serialize_decision(result: DecisionResult) -> dict:
    return {
        "action": result.action,
        "capture_ratio": result.capture_ratio,
        "rationale": result.rationale,
        "findings": [
            {"code": finding.code, "severity": finding.severity, "message": finding.message}
            for finding in result.findings
        ],
        "manual_review_required": result.manual_review_required,
    }


def _system_actor() -> ActorContext:
    """System-opened review case için user/token taşımayan actor projection'ı."""

    return ActorContext(actor_type="anonymous", auth_method="none")


def _open_video_review_case_if_needed(
    conn: Connection,
    *,
    transaction_id: str,
    lifecycle_version: str,
    result: DecisionResult,
) -> None:
    """Account video anomaly'sini idempotent blocking settlement review'e bağlar."""

    if lifecycle_version != "account_v2" or not result.manual_review_required:
        return
    if not {
        "VIDEO_COUNT_DIVERGENCE",
        "VIDEO_DAMAGE_MATCHED",
    }.intersection(finding.code for finding in result.findings):
        return

    video_row = evidence_repo.latest_for_type(
        conn, transaction_id=transaction_id, evidence_type="video"
    )
    source_id = video_row["id"] if video_row is not None else transaction_id
    review_service.open_case(
        conn,
        transaction_id=transaction_id,
        phase="settlement",
        source_type="video",
        source_id=source_id,
        reason_code="VIDEO_ADVISORY_ANOMALY",
        title="Video teslimat anomalisi manuel inceleme bekliyor",
        description="Video advisory sinyali release öncesi insan incelemesi gerektiriyor.",
        severity="blocking",
        actor_context=_system_actor(),
    )


def _release_blockers(
    conn: Connection, transaction_id: str
) -> tuple[bool, bool]:
    """Tek release guard için settlement review + transaction-wide dispute."""

    return (
        review_service.has_blocking_case(conn, transaction_id, phase="settlement"),
        disputes_repo.has_open_dispute(
            conn, transaction_id=transaction_id, milestone_id=None
        ),
    )


def _apply_release_guard_findings(
    decision: dict, *, review_blocked: bool, dispute_blocked: bool
) -> dict:
    """Provider'a gitmeden deterministic kararı güvenli hold projection'ına çevirir."""

    if not review_blocked and not dispute_blocked:
        return decision

    findings = list(decision.get("findings") or [])
    if review_blocked:
        findings.append(
            {
                "code": "REVIEW_BLOCKING_RELEASE",
                "severity": "blocking",
                "message": "Açık settlement review case release'i blokluyor.",
            }
        )
    if dispute_blocked:
        findings.append(
            {
                "code": "DISPUTE_BLOCKING_RELEASE",
                "severity": "blocking",
                "message": "Açık dispute release'i blokluyor.",
            }
        )
    return {
        **decision,
        "action": "hold",
        "capture_ratio": 0.0,
        "manual_review_required": True,
        "findings": findings,
        "rationale": "Release guard açık review/dispute nedeniyle hold üretti.",
    }


def evaluate_settlement(conn: Connection, transaction_id: str, settings: Settings) -> dict | None:
    """Fonlanmış işlemi kilitli policy ve güncel kanıtlarla bir kez değerlendirir.

    Çağıran transaction'ın commit sorumluluğunu taşır. Fonlanmamış veya artık
    sonuçlanmış işlemler sessizce atlanır; provider yalnız capture aksiyonunda
    ve havuz ödemesi hâlâ ``pool`` durumundayken çağrılır.
    """
    transaction = conn.execute(
        "SELECT state, lifecycle_version FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    if transaction is None:
        return None
    if transaction["lifecycle_version"] == "account_v2":
        if transaction["state"] != "active":
            return None
    elif transaction["state"] not in _LEGACY_FUNDED_STATES:
        return None
    if not _has_both_approvals(conn, transaction_id):
        return None

    policy = load_tracking_policy(conn, transaction_id)
    if policy is None or policy.status.value != "locked":
        return None

    extraction = _load_extraction(conn, transaction_id)
    if extraction is None:
        return None

    requirements = resolve_effective_requirements(extraction, policy)
    delivery_evidence = evidence_records_service.collect_transaction_delivery_evidence(
        conn, transaction_id
    )
    result = decide(
        extraction,
        requirements,
        delivery_evidence,
        video_confidence_threshold=settings.video_advisory_confidence_threshold,
        divergence_threshold=0.10,
    )
    decision = _serialize_decision(result)

    _open_video_review_case_if_needed(
        conn,
        transaction_id=transaction_id,
        lifecycle_version=transaction["lifecycle_version"],
        result=result,
    )

    review_blocked, dispute_blocked = _release_blockers(conn, transaction_id)
    decision = _apply_release_guard_findings(
        decision, review_blocked=review_blocked, dispute_blocked=dispute_blocked
    )

    if decision["action"] not in {"capture", "partial_capture"}:
        if transaction["lifecycle_version"] != "account_v2":
            conn.execute(
                "UPDATE transactions SET state = 'evidence_pending' WHERE id = ?",
                (transaction_id,),
            )
        emit(conn, transaction_id, "payment_decision_created", decision, "system")
        return decision

    provider = make_payment_provider(settings, conn)
    payment_status = provider.get_payment_status(other_trx_code=transaction_id)
    payment_data = payment_status.get("Data") or {}
    if not payment_data.get("IsSuccessful") or payment_data.get("status") != "pool":
        return None

    approval = provider.approve_pool_payment(
        other_trx_code=transaction_id, capture_ratio=result.capture_ratio
    )
    if not (approval.get("Data") or {}).get("IsSuccessful"):
        return None

    emit(conn, transaction_id, "payment_decision_created", decision, "system")
    emit(
        conn,
        transaction_id,
        "mock_payment_executed",
        {"action": result.action, "capture_ratio": result.capture_ratio},
        "system",
    )
    if transaction["lifecycle_version"] != "account_v2":
        conn.execute("UPDATE transactions SET state = 'decided' WHERE id = ?", (transaction_id,))
    return decision
