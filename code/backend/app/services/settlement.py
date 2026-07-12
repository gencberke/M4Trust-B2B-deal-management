"""Kilitli policy ve kanıtlardan deterministik ödeme mutabakatını yürütür.

Dual yol (Faz 6C): ``legacy_v1`` bugünkü ``decide()`` + tek-pool ``MockMokaProvider``
davranışını bit-bit korur; ``account_v2`` ratified package + persisted milestone/
funding-unit üzerinden evidence → ``MilestoneEvaluator`` → ``ReleaseCoordinator`` →
``PaymentGateway`` yolunu kullanır (funding-unit başına ayrı approve). Tek release
guard bu modüldedir; router provider çağırmaz.
"""

from __future__ import annotations

import json
from sqlite3 import Connection

from backend.app.config import Settings
from backend.app.eventbus import emit
from backend.app.repositories import disputes as disputes_repo
from backend.app.repositories import evidence as evidence_repo
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.repositories import milestones as milestones_repo
from backend.app.repositories import ratifications as ratifications_repo
from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.schemas.extraction import ExtractionJSON, RequiredEvidence
from backend.app.schemas.payments import ReleaseMode
from backend.app.services.decision import DecisionResult, decide
from backend.app.services.effective_requirements import resolve_effective_requirements
from backend.app.services import evidence_records as evidence_records_service
from backend.app.services import milestone_decision as md
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from backend.app.services.payment_provider import make_payment_provider
from backend.app.services.payments import release_coordinator
from backend.app.services.ratification_package import get_current as _get_current_package
from backend.app.services.tracking_policy import load_tracking_policy

_LEGACY_FUNDED_STATES = {"active", "evidence_pending"}
_DIVERGENCE_THRESHOLD = 0.10


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


def evaluate_settlement(
    conn: Connection, transaction_id: str, settings: Settings, *, gateway=None
) -> dict | None:
    """Fonlanmış işlemi kilitli policy ve güncel kanıtlarla bir kez değerlendirir.

    Çağıran transaction'ın commit sorumluluğunu taşır. Fonlanmamış veya artık
    sonuçlanmış işlemler sessizce atlanır. ``account_v2`` işlemler funding-unit
    release yoluna (Faz 6C) yönlendirilir; ``legacy_v1`` bugünkü tek-pool
    davranışını bit-bit korur. ``gateway`` yalnız account yolu için opsiyonel
    deterministik test injection'ıdır.
    """
    transaction = conn.execute(
        "SELECT state, lifecycle_version FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    if transaction is None:
        return None
    if transaction["lifecycle_version"] == "account_v2":
        return _evaluate_account_settlement(conn, transaction_id, settings, gateway=gateway)
    if transaction["state"] not in _LEGACY_FUNDED_STATES:
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


# ---------------------------------------------------------------------------
# account_v2 settlement yolu (Faz 6C) — funding-unit release
# ---------------------------------------------------------------------------


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _contract_quantity(extraction: ExtractionJSON | None) -> int:
    if extraction is None:
        return 0
    total = sum(goods.quantity for goods in extraction.commercial_terms.goods)
    return int(total) if total > 0 else 0


def _package_policy_locked(package) -> bool:
    """Kilitli policy readiness'i package SNAPSHOT'ından okur (legacy approvals değil)."""

    try:
        payload = json.loads(package.canonical_payload_json)
    except (TypeError, ValueError):
        return False
    snapshot = ((payload.get("tracking_policy") or {}).get("snapshot")) or {}
    return snapshot.get("status") == "locked"


def _account_ready_package(conn: Connection, transaction_id: str):
    """Account release readiness — legacy approvals tablosunu KULLANMAZ.

    package complete + buyer&seller ratification + policy snapshot locked +
    funding unit'ler pool_created. Değilse ``None`` (sessiz atlama).
    """

    package = _get_current_package(conn, transaction_id)
    if package is None or package.status.value != "complete":
        return None
    roles = ratifications_repo.distinct_roles_for_package(conn, package.id)
    if not {"buyer", "seller"} <= roles:
        return None
    if not _package_policy_locked(package):
        return None
    units = [
        unit
        for unit in funding_units_repo.list_for_transaction(conn, transaction_id)
        if unit["ratification_package_id"] == package.id
    ]
    if not units or not all(
        unit["status"] in {"pool_created", "approval_pending", "approval_unknown", "approved"}
        for unit in units
    ):
        return None
    # İlerletilebilecek en az bir unit olmalı: yeni release için pool_created,
    # ya da belirsiz kalmış (approval_unknown) bir unit'in reconcile'ı. Hepsi
    # zaten approved ise yapılacak iş yoktur.
    if not any(
        unit["status"] in {"pool_created", "approval_unknown"} for unit in units
    ):
        return None
    return package


def _milestone_required_evidence(required_evidence_json: str) -> frozenset[RequiredEvidence]:
    result = set()
    try:
        values = json.loads(required_evidence_json)
    except (TypeError, ValueError):
        return frozenset()
    for value in values or []:
        try:
            result.add(RequiredEvidence(value))
        except ValueError:
            continue
    return frozenset(result)


def _unit_quantity_threshold(eligibility_payload: dict, *, contract_quantity: int) -> int | None:
    """fixed_tranches unit'i için kümülatif miktar eşiğini türetir.

    Compiler yalnız (tranche_index, tranche_count) yazar; caller eşiği contract
    miktarından deterministik biçimde hesaplar (Moka §3.5, "100 koli / 4×25"):
    threshold = ceil(tranche_index / tranche_count * contract_quantity).
    """

    tranche_index = eligibility_payload.get("tranche_index")
    tranche_count = eligibility_payload.get("tranche_count")
    if not isinstance(tranche_index, int) or not isinstance(tranche_count, int):
        return None
    if tranche_count <= 0 or contract_quantity <= 0:
        return None
    return (tranche_index * contract_quantity + tranche_count - 1) // tranche_count


def _verified_evidence_rows(conn: Connection, transaction_id: str, milestone_id: str):
    """Yalnız bu milestone'a bağlı verified kanıtı döndürür.

    Transaction-level NULL kanıtlar 06X sonrasında eligibility'ye broadcast
    edilmez; evidence service aktif package'ta tek adayı otomatik bağlar,
    birden fazla adayda ise kanıt submit'ini fail-closed reddeder.
    """

    return conn.execute(
        "SELECT evidence_type, payload_json FROM evidence_records "
        "WHERE transaction_id = ? AND verification_status = 'verified' "
        "AND milestone_id = ? "
        "ORDER BY created_at ASC, id ASC",
        (transaction_id, milestone_id),
    ).fetchall()


def _advisory_video_rows(conn: Connection, transaction_id: str, milestone_id: str):
    """Bu milestone'a bağlı verified veya review_required video kayıtları.

    Yüksek güvenli hasar sinyali evidence'ı ``review_required`` yapar (ingestion);
    bu kayıt required-evidence'ı TAMAMLAMAZ ama hold/review sinyalini taşımalıdır,
    aksi halde hasarlı teslimat release'i durdurmayabilir (blocker)."""

    return conn.execute(
        "SELECT payload_json FROM evidence_records "
        "WHERE transaction_id = ? AND evidence_type = 'video' "
        "AND verification_status IN ('verified', 'review_required') "
        "AND milestone_id = ? "
        "ORDER BY created_at ASC, id ASC",
        (transaction_id, milestone_id),
    ).fetchall()


def _latest_video_for_milestone(
    conn: Connection, transaction_id: str, milestone_id: str
):
    """Review source'u için bu milestone'un en yeni reddedilmemiş videosu."""

    return conn.execute(
        "SELECT * FROM evidence_records WHERE transaction_id = ? "
        "AND evidence_type = 'video' AND milestone_id = ? "
        "AND verification_status != 'rejected' "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        (transaction_id, milestone_id),
    ).fetchone()


def _build_video_advisory(
    video_rows, *, cumulative_qty: int | None, contract_quantity: int, threshold: float
) -> md.VideoAdvisorySummary:
    if not video_rows:
        return md.VideoAdvisorySummary(provided=False)
    try:
        payload = json.loads(video_rows[-1]["payload_json"])
    except (TypeError, ValueError):
        return md.VideoAdvisorySummary(provided=True)
    confidence = _as_float(payload.get("confidence"))
    high_conf = confidence is not None and confidence >= threshold
    divergence = False
    if high_conf and contract_quantity > 0 and cumulative_qty is not None:
        video_qty = _as_float(payload.get("unit_count"))
        if video_qty is not None:
            divergence = (
                abs(cumulative_qty - video_qty) / contract_quantity > _DIVERGENCE_THRESHOLD
            )
    damage = False
    if high_conf:
        for signal in payload.get("damage_signals") or []:
            # Ingestion güvenli projeksiyonu `matched_box` alanını yazar.
            if (
                isinstance(signal, dict)
                and signal.get("matched_box")
                and (_as_float(signal.get("confidence")) or 0.0) >= threshold
            ):
                damage = True
                break
    return md.VideoAdvisorySummary(
        provided=True,
        high_confidence=high_conf,
        count_divergence_detected=divergence,
        damage_matched=damage,
    )


def _trigger_satisfied(trigger_type: str, verified_types: frozenset[str]) -> bool:
    """Milestone trigger fact'ini deterministik çözer (caller sorumluluğu, §6B).

    approval → ratification precondition (settlement readiness zaten garanti eder).
    e_invoice/delivery_video → ilgili verified kanıt. manual_review → en az bir
    verified teslim kanıtı. Bilinmeyen trigger → False (evaluator ayrıca fail-closed).
    """

    if trigger_type == "approval":
        return True
    if trigger_type == "e_invoice":
        return bool({"e_invoice", "e_irsaliye"} & verified_types)
    if trigger_type == "delivery_video":
        return "video" in verified_types
    if trigger_type == "manual_review":
        return bool({"e_irsaliye", "e_invoice", "video"} & verified_types)
    return False


def _build_milestone_evidence_set(
    conn: Connection,
    transaction_id: str,
    milestone_row,
    *,
    contract_quantity: int,
    settings: Settings,
) -> md.MilestoneEvidenceSet:
    rows = _verified_evidence_rows(conn, transaction_id, milestone_row["id"])
    verified_types = frozenset(row["evidence_type"] for row in rows)
    e_irsaliye_rows = [row for row in rows if row["evidence_type"] == "e_irsaliye"]
    cumulative_qty: int | None = None
    if e_irsaliye_rows:
        # Her verified e-irsaliye bir teslim DELTA'sıdır; kümülatif doğrulanmış
        # miktar tüm verified e-irsaliye delta'larının toplamıdır (video asla
        # katkı yapmaz). Idempotent submit aynı satırı çift saymaz.
        total = 0.0
        for row in e_irsaliye_rows:
            qty = _as_float(json.loads(row["payload_json"]).get("delivered_quantity"))
            if qty is not None:
                total += qty
        cumulative_qty = int(total)

    video_advisory = _build_video_advisory(
        _advisory_video_rows(conn, transaction_id, milestone_row["id"]),
        cumulative_qty=cumulative_qty,
        contract_quantity=contract_quantity,
        threshold=settings.video_advisory_confidence_threshold,
    )

    units = funding_units_repo.list_for_milestone(conn, milestone_row["id"])
    unit_eligibility = []
    for unit in units:
        try:
            payload = json.loads(unit["eligibility_payload_json"])
        except (TypeError, ValueError):
            payload = {}
        unit_eligibility.append(
            md.FundingUnitEligibility(
                funding_unit_id=unit["id"],
                sequence=unit["sequence"],
                quantity_threshold=_unit_quantity_threshold(
                    payload, contract_quantity=contract_quantity
                ),
                already_released=unit["status"] == "approved",
            )
        )

    return md.MilestoneEvidenceSet(
        verified_evidence_types=verified_types,
        cumulative_verified_quantity=cumulative_qty,
        video_advisory=video_advisory,
        funding_units=tuple(unit_eligibility),
        trigger_satisfied=_trigger_satisfied(milestone_row["trigger_type"], verified_types),
    )


def _build_review_state(
    conn: Connection, transaction_id: str, milestone_id: str
) -> md.MilestoneReviewState:
    review_blocked = review_service.has_blocking_case(
        conn, transaction_id, phase="settlement"
    ) or review_service.has_blocking_case(conn, transaction_id, phase="payment")
    dispute_blocked = disputes_repo.has_open_dispute(
        conn, transaction_id=transaction_id, milestone_id=milestone_id
    )
    return md.MilestoneReviewState(
        has_blocking_review=review_blocked, has_blocking_dispute=dispute_blocked
    )


def _open_account_video_review_if_needed(
    conn: Connection, *, transaction_id: str, milestone_id: str, decision: md.MilestoneDecision
) -> None:
    """Video advisory anomalisini idempotent blocking settlement review'e bağlar."""

    if not decision.manual_review_required:
        return
    if not {"VIDEO_COUNT_DIVERGENCE", "VIDEO_DAMAGE_MATCHED"}.intersection(
        finding.code for finding in decision.findings
    ):
        return
    if review_service.has_blocking_case(conn, transaction_id, phase="settlement"):
        return
    video_row = _latest_video_for_milestone(conn, transaction_id, milestone_id)
    source_id = video_row["id"] if video_row is not None else milestone_id
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


def _evaluate_account_settlement(
    conn: Connection, transaction_id: str, settings: Settings, *, gateway=None
) -> dict | None:
    tx = conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    if tx is None or tx["state"] != "active":
        return None
    package = _account_ready_package(conn, transaction_id)
    if package is None:
        return None

    extraction = _load_extraction(conn, transaction_id)
    contract_quantity = _contract_quantity(extraction)

    milestones = milestones_repo.list_for_package(conn, package.id)
    eligible_unit_ids: list[str] = []
    milestone_reports: list[dict] = []
    for milestone_row in milestones:
        milestone = md.Milestone(
            milestone_id=milestone_row["id"],
            release_mode=ReleaseMode(milestone_row["release_mode"]),
            required_evidence=_milestone_required_evidence(
                milestone_row["required_evidence_json"]
            ),
            trigger_type=milestone_row["trigger_type"],
        )
        evidence_set = _build_milestone_evidence_set(
            conn, transaction_id, milestone_row,
            contract_quantity=contract_quantity, settings=settings,
        )
        review_state = _build_review_state(conn, transaction_id, milestone_row["id"])
        decision = md.evaluate_milestone(milestone, evidence_set, review_state)
        _open_account_video_review_if_needed(
            conn, transaction_id=transaction_id, milestone_id=milestone_row["id"],
            decision=decision,
        )
        # Video review case açıldıysa bu turda ilgili unit'ler eligible sayılmaz.
        if decision.manual_review_required:
            eligible_ids: tuple[str, ...] = ()
        else:
            eligible_ids = decision.release_candidate.funding_unit_ids
        eligible_unit_ids.extend(eligible_ids)
        milestone_reports.append(
            {
                "milestone_id": milestone_row["id"],
                "status": decision.status,
                "eligible_unit_ids": list(eligible_ids),
                "manual_review_required": decision.manual_review_required,
            }
        )

    # approval_unknown unit'ler (approve timeout) release candidate olmasalar bile
    # reconcile edilmelidir; ReleaseCoordinator önce detail sorgular (kör approve yok).
    reconcile_ids = [
        unit["id"]
        for unit in funding_units_repo.list_for_transaction(conn, transaction_id)
        if unit["ratification_package_id"] == package.id
        and unit["status"] == "approval_unknown"
    ]
    release_ids = list(dict.fromkeys([*eligible_unit_ids, *reconcile_ids]))

    if gateway is None:
        from backend.app.services.payments.funding_coordinator import make_payment_gateway

        gateway = make_payment_gateway(settings, conn)

    release = release_coordinator.release_units(
        conn,
        transaction_id=transaction_id,
        unit_ids=tuple(release_ids),
        gateway=gateway,
        actor_context=_system_actor(),
    )

    return {
        "lifecycle_version": "account_v2",
        "milestones": milestone_reports,
        "approved_unit_ids": list(release.approved_unit_ids),
        "unknown_unit_ids": list(release.unknown_unit_ids),
        "failed_unit_ids": list(release.failed_unit_ids),
        "settled": release.settled,
    }
