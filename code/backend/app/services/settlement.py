"""Kilitli policy ve kanıtlardan deterministik ödeme mutabakatını yürütür."""

from __future__ import annotations

import json
from sqlite3 import Connection, Row

from backend.app.config import Settings
from backend.app.eventbus import emit
from backend.app.schemas.extraction import ExtractionJSON
from backend.app.services.decision import DeliveryEvidence, DecisionResult, decide
from backend.app.services.effective_requirements import resolve_effective_requirements
from backend.app.services.payment_provider import make_payment_provider
from backend.app.services.tracking_policy import load_tracking_policy

_FUNDED_STATES = {"active", "evidence_pending"}


def _load_extraction(conn: Connection, transaction_id: str) -> ExtractionJSON | None:
    row = conn.execute(
        "SELECT extraction_json FROM extracted_rules WHERE transaction_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (transaction_id,),
    ).fetchone()
    if row is None or row["extraction_json"] is None:
        return None
    try:
        return ExtractionJSON.model_validate(json.loads(row["extraction_json"]))
    except (TypeError, ValueError):
        return None


def _has_both_approvals(conn: Connection, transaction_id: str) -> bool:
    parties = {
        row["party"]
        for row in conn.execute(
            "SELECT DISTINCT party FROM approvals WHERE transaction_id = ?",
            (transaction_id,),
        ).fetchall()
    }
    return {"buyer", "seller"} <= parties


def _decode_event_payload(row: Row) -> dict | None:
    for column in ("payload_json", "data_json", "payload", "data"):
        if column not in row.keys() or row[column] is None:
            continue
        try:
            value = json.loads(row[column]) if isinstance(row[column], str) else row[column]
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _latest_evidence_payload(
    conn: Connection, transaction_id: str, event_term: str
) -> dict | None:
    row = conn.execute(
        "SELECT * FROM events WHERE transaction_id = ? AND event_type LIKE ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (transaction_id, f"%{event_term}%"),
    ).fetchone()
    return None if row is None else _decode_event_payload(row)


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


def evaluate_settlement(conn: Connection, transaction_id: str, settings: Settings) -> dict | None:
    """Fonlanmış işlemi kilitli policy ve güncel kanıtlarla bir kez değerlendirir.

    Çağıran transaction'ın commit sorumluluğunu taşır. Fonlanmamış veya artık
    sonuçlanmış işlemler sessizce atlanır; provider yalnız capture aksiyonunda
    ve havuz ödemesi hâlâ ``pool`` durumundayken çağrılır.
    """
    transaction = conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    if transaction is None or transaction["state"] not in _FUNDED_STATES:
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
    result = decide(
        extraction,
        requirements,
        DeliveryEvidence(
            e_irsaliye=_latest_evidence_payload(conn, transaction_id, "e_irsaliye"),
            video=_latest_evidence_payload(conn, transaction_id, "video"),
        ),
        video_confidence_threshold=settings.video_advisory_confidence_threshold,
        divergence_threshold=0.10,
    )
    decision = _serialize_decision(result)

    if result.action not in {"capture", "partial_capture"}:
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
    conn.execute("UPDATE transactions SET state = 'decided' WHERE id = ?", (transaction_id,))
    return decision
