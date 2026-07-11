"""Frozen `ReviewService` davranış testleri: `open_case`, `record_action`,
`resolve_case`, `has_blocking_case` + `open_validator_case` yardımcısı."""

from __future__ import annotations

import pytest

from backend.app.services import review as svc
from backend.app.services.access_control import ActorContext
from participants_fixtures import create_test_transaction
from reviews_fixtures import make_reviews_db


@pytest.fixture()
def conn():
    connection = make_reviews_db()
    try:
        yield connection
    finally:
        connection.close()


def actor(user_id="u1", platform_role=None) -> ActorContext:
    return ActorContext(actor_type="user", user_id=user_id, platform_role=platform_role, request_id="req-1")


def _open(conn, tx_id, *, severity="blocking", reason_code="RC1", phase="pre_ratification", source_id="s1"):
    return svc.open_case(
        conn,
        transaction_id=tx_id,
        phase=phase,
        source_type="validator",
        source_id=source_id,
        reason_code=reason_code,
        title="t",
        description="d",
        severity=severity,
        actor_context=actor(),
    )


# --- open_case ------------------------------------------------------------------


def test_open_case_success(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id)
    assert case.status.value == "open"
    assert case.severity.value == "blocking"
    assert case.transaction_id == tx_id


def test_open_case_writes_audit_row(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id)
    row = conn.execute(
        "SELECT * FROM audit_events WHERE action = 'review.case_opened'"
    ).fetchone()
    assert row is not None
    assert row["transaction_id"] == tx_id
    assert row["target_id"] == case.id


def test_open_case_duplicate_blocking_is_idempotent(conn) -> None:
    tx_id = create_test_transaction(conn)
    first = _open(conn, tx_id, reason_code="DUP")
    second = _open(conn, tx_id, reason_code="DUP")
    assert first.id == second.id
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM review_cases WHERE transaction_id = ?", (tx_id,)
    ).fetchone()["n"]
    assert count == 1


def test_open_case_warning_is_not_deduped(conn) -> None:
    tx_id = create_test_transaction(conn)
    first = _open(conn, tx_id, severity="warning", reason_code="W1")
    second = _open(conn, tx_id, severity="warning", reason_code="W1")
    assert first.id != second.id


def test_open_case_after_resolution_opens_new_case(conn) -> None:
    tx_id = create_test_transaction(conn)
    first = _open(conn, tx_id, reason_code="R1")
    svc.resolve_case(conn, case_id=first.id, actor_context=actor(platform_role="reviewer"), resolution_code="fixed")
    second = _open(conn, tx_id, reason_code="R1")
    assert second.id != first.id


# --- has_blocking_case -----------------------------------------------------------


def test_has_blocking_case_true_and_false(conn) -> None:
    tx_id = create_test_transaction(conn)
    assert svc.has_blocking_case(conn, tx_id) is False
    _open(conn, tx_id)
    assert svc.has_blocking_case(conn, tx_id) is True


def test_has_blocking_case_phase_filter(conn) -> None:
    tx_id = create_test_transaction(conn)
    _open(conn, tx_id, phase="settlement", reason_code="S1")
    assert svc.has_blocking_case(conn, tx_id, phase="pre_ratification") is False
    assert svc.has_blocking_case(conn, tx_id, phase="settlement") is True


def test_has_blocking_case_ignores_warning_severity(conn) -> None:
    tx_id = create_test_transaction(conn)
    _open(conn, tx_id, severity="warning", reason_code="W1")
    assert svc.has_blocking_case(conn, tx_id) is False


def test_has_blocking_case_ignores_resolved(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id, reason_code="R1")
    svc.resolve_case(conn, case_id=case.id, actor_context=actor(platform_role="admin"), resolution_code="fixed")
    assert svc.has_blocking_case(conn, tx_id) is False


# --- record_action: comment (non state-changing) ---------------------------------


def test_comment_does_not_change_status(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id)
    action = svc.record_action(conn, case_id=case.id, actor_context=actor(), action="comment", payload={"comment": "ok"})
    assert action.action.value == "comment"
    reloaded = svc.list_cases(conn, tx_id)[0]
    assert reloaded.status.value == "open"


# --- record_action: state-changing --------------------------------------------


def test_request_evidence_changes_status(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id)
    svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="reviewer"), action="request_evidence")
    reloaded = svc.list_cases(conn, tx_id)[0]
    assert reloaded.status.value == "evidence_requested"


def test_escalate_changes_status(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id)
    svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="admin"), action="escalate")
    reloaded = svc.list_cases(conn, tx_id)[0]
    assert reloaded.status.value == "escalated"


def test_resolve_reject_changes_status_and_records_resolution(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id)
    svc.record_action(
        conn, case_id=case.id, actor_context=actor("reviewer-1", "reviewer"),
        action="resolve_reject", payload={"resolution_code": "CONTRACT_VIOLATION"},
    )
    reloaded = svc.list_cases(conn, tx_id)[0]
    assert reloaded.status.value == "resolved"
    assert reloaded.resolution_code == "CONTRACT_VIOLATION"
    assert reloaded.resolved_by_user_id == "reviewer-1"
    assert reloaded.resolved_at is not None


def test_cancel_changes_status_to_cancelled(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id)
    svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="admin"), action="cancel")
    reloaded = svc.list_cases(conn, tx_id)[0]
    assert reloaded.status.value == "cancelled"


def test_closed_case_rejects_further_state_changing_action(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id)
    svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="admin"), action="cancel")
    with pytest.raises(svc.ReviewCaseClosedError):
        svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="admin"), action="escalate")


def test_closed_case_still_allows_comment(conn) -> None:
    """Kural: 'comment append edilebilir fakat case state'ini değiştirmez' --
    yalnız STATE-CHANGING action'lar kapalı case'te reddedilir, comment değil."""
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id)
    svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="admin"), action="cancel")
    action = svc.record_action(conn, case_id=case.id, actor_context=actor(), action="comment", payload={"comment": "note"})
    assert action.action.value == "comment"


# --- Wave A güvenlik sınırı: resolve_continue -------------------------------------


def test_resolve_continue_on_blocking_case_is_forbidden(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id, severity="blocking")
    with pytest.raises(svc.ReviewActionForbiddenError):
        svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="reviewer"), action="resolve_continue")
    reloaded = svc.list_cases(conn, tx_id)[0]
    assert reloaded.status.value == "open"


def test_resolve_continue_on_warning_case_succeeds(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id, severity="warning")
    svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="reviewer"), action="resolve_continue")
    reloaded = svc.list_cases(conn, tx_id)[0]
    assert reloaded.status.value == "resolved"


# --- concurrency / conditional resolve --------------------------------------------


def test_concurrent_resolve_case_second_call_raises(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id)
    svc.resolve_case(conn, case_id=case.id, actor_context=actor(platform_role="admin"), resolution_code="fixed")
    with pytest.raises(svc.ReviewCaseClosedError):
        svc.resolve_case(conn, case_id=case.id, actor_context=actor(platform_role="admin"), resolution_code="fixed-again")


def test_resolve_case_not_found_raises(conn) -> None:
    with pytest.raises(svc.ReviewCaseNotFoundError):
        svc.resolve_case(conn, case_id="does-not-exist", actor_context=actor(platform_role="admin"), resolution_code="x")


def test_record_action_case_not_found_raises(conn) -> None:
    with pytest.raises(svc.ReviewCaseNotFoundError):
        svc.record_action(conn, case_id="does-not-exist", actor_context=actor(), action="comment")


# --- audit / rollback --------------------------------------------------------------


def test_business_mutation_and_audit_rollback_together(conn) -> None:
    tx_id = create_test_transaction(conn)
    conn.commit()

    _open(conn, tx_id)
    conn.rollback()

    case_count = conn.execute("SELECT COUNT(*) AS n FROM review_cases").fetchone()["n"]
    audit_count = conn.execute(
        "SELECT COUNT(*) AS n FROM audit_events WHERE action = 'review.case_opened'"
    ).fetchone()["n"]
    assert case_count == 0
    assert audit_count == 0


def test_audit_metadata_does_not_contain_comment_text(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id)
    svc.record_action(
        conn, case_id=case.id, actor_context=actor(), action="comment",
        payload={"comment": "This is a free-text comment with details"},
    )
    rows = conn.execute("SELECT metadata_json FROM audit_events").fetchall()
    for row in rows:
        assert "free-text comment with details" not in row["metadata_json"]


# --- open_validator_case -----------------------------------------------------------


def test_open_validator_case_pass_opens_nothing(conn) -> None:
    tx_id = create_test_transaction(conn)
    result = svc.open_validator_case(
        conn, transaction_id=tx_id, source_id="rs-1", validator_status="PASS",
        finding_codes=[], actor_context=actor(),
    )
    assert result is None
    assert svc.has_blocking_case(conn, tx_id) is False


def test_open_validator_case_needs_review_opens_blocking_case(conn) -> None:
    tx_id = create_test_transaction(conn)
    result = svc.open_validator_case(
        conn, transaction_id=tx_id, source_id="rs-1", validator_status="NEEDS_REVIEW",
        finding_codes=["PERCENTAGE_SUM"], actor_context=actor(),
    )
    assert result is not None
    assert result.severity.value == "blocking"
    assert result.phase.value == "pre_ratification"


def test_open_validator_case_duplicate_call_does_not_duplicate(conn) -> None:
    tx_id = create_test_transaction(conn)
    first = svc.open_validator_case(
        conn, transaction_id=tx_id, source_id="rs-1", validator_status="NEEDS_REVIEW",
        finding_codes=["X"], actor_context=actor(),
    )
    second = svc.open_validator_case(
        conn, transaction_id=tx_id, source_id="rs-1", validator_status="NEEDS_REVIEW",
        finding_codes=["X"], actor_context=actor(),
    )
    assert first.id == second.id


def test_open_validator_case_description_has_no_raw_pii(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = svc.open_validator_case(
        conn, transaction_id=tx_id, source_id="rs-1", validator_status="NEEDS_REVIEW",
        finding_codes=["PERCENTAGE_SUM"], actor_context=actor(),
    )
    # yalnız deterministik finding kodları görünmeli, ham exception/validator mesajı değil
    assert "PERCENTAGE_SUM" in case.description
    assert "Traceback" not in case.description
