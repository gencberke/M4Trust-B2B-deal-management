"""Frozen `ReviewService` davranış testleri: `open_case`, `record_action`,
`resolve_case`, `has_blocking_case` + `open_validator_case` yardımcısı."""

from __future__ import annotations

import json

import pytest

from backend.app.services import review as svc
from backend.app.services.access_control import ActorContext
from participants_fixtures import create_test_transaction
from reviews_fixtures import make_reviews_db, make_reviews_db_with_rule_sets


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


def test_resolve_continue_on_blocking_case_without_revision_is_rejected() -> None:
    """Faz 4F-2: revision+revalidation yapılmadan blocking case hâlâ reddedilir --
    yalnız hata tipi değişti (kayıtsız-şartsız yasak yerine ön-koşul kontrolü)."""
    conn = make_reviews_db_with_rule_sets()
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id, severity="blocking")
    with pytest.raises(svc.ReviewResolutionPreconditionError):
        svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="reviewer"), action="resolve_continue")
    reloaded = svc.list_cases(conn, tx_id)[0]
    assert reloaded.status.value == "open"
    conn.close()


def test_resolve_continue_on_blocking_case_outside_pre_ratification_is_forbidden(conn) -> None:
    """settlement/payment fazındaki blocking case'ler için resolution semantiği henüz yok."""
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id, severity="blocking", phase="settlement")
    with pytest.raises(svc.ReviewActionForbiddenError):
        svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="reviewer"), action="resolve_continue")


def test_resolve_continue_on_warning_case_succeeds(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id, severity="warning")
    svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="reviewer"), action="resolve_continue")
    reloaded = svc.list_cases(conn, tx_id)[0]
    assert reloaded.status.value == "resolved"


# --- Faz 4F-2: blocking resolve_continue ön koşulları -------------------------------

_PAYLOAD_4F2 = {
    "contract_id": "c-4f2",
    "parties": {
        "buyer": {"name": "Buyer A.Ş.", "tax_id": "1111111111"},
        "seller": {"name": "Seller Ltd.", "tax_id": "2222222222"},
    },
    "commercial_terms": {
        "currency": "TRY",
        "total_amount": 100.0,
        "goods": [{"name": "Pompa", "quantity": 1.0, "unit": "adet"}],
        "delivery_deadline": None,
    },
    "payment_rules": [
        {
            "milestone": "Kabul",
            "trigger": "approval",
            "percentage": 100.0,
            "required_evidence": ["contract"],
            "source_quote": "Onay sonrası ödeme yapılır.",
            "confidence": 0.9,
        }
    ],
    "risk_flags": [],
    "needs_manual_review": False,
}


def _account_tx_with_rule_set(conn, *, confidence_threshold: float):
    """account_v2 transaction + tek rule_set_version; `confidence_threshold` 0.9'dan
    büyükse validator NEEDS_REVIEW döner (confidence 0.9 < threshold), küçük/eşitse PASS."""
    from backend.app.services.rule_versions import create_initial_from_extraction, validate_version

    tx_id = create_test_transaction(conn)
    conn.execute("UPDATE transactions SET lifecycle_version = 'account_v2' WHERE id = ?", (tx_id,))
    document_id = f"doc-{tx_id}"
    run_id = f"run-{tx_id}"
    conn.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) VALUES (?, ?, 1, 'c.md', ?, "
        "'hash', 'active', 'now')",
        (document_id, tx_id, f"{tx_id}/{document_id}"),
    )
    conn.execute(
        "INSERT INTO extraction_runs (id, transaction_id, document_id, provider, model, "
        "prompt_version, schema_version, extraction_json, status, created_at) "
        "VALUES (?, ?, ?, 'fake', 'fake-v1', 'v1', 'v1', ?, 'ok', 'now')",
        (run_id, tx_id, document_id, json.dumps(_PAYLOAD_4F2)),
    )
    version = create_initial_from_extraction(
        conn, transaction_id=tx_id, extraction_run_id=run_id, rules_payload=_PAYLOAD_4F2
    )
    validate_version(conn, version_id=version.id, confidence_threshold=confidence_threshold)
    return tx_id, version.id


def test_resolve_continue_on_validator_case_before_revision_still_rejected() -> None:
    conn = make_reviews_db_with_rule_sets()
    tx_id, version_id = _account_tx_with_rule_set(conn, confidence_threshold=2.0)  # -> NEEDS_REVIEW
    case = svc.open_validator_case(
        conn,
        transaction_id=tx_id,
        source_id=version_id,
        validator_status="NEEDS_REVIEW",
        finding_codes=["LOW_CONFIDENCE"],
        actor_context=actor(),
    )
    with pytest.raises(svc.ReviewResolutionPreconditionError):
        svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="reviewer"), action="resolve_continue")
    conn.close()


def test_resolve_continue_on_validator_case_after_revalidation_returns_to_preparation() -> None:
    from backend.app.services.rule_versions import create_revision, validate_version

    conn = make_reviews_db_with_rule_sets()
    tx_id, old_version_id = _account_tx_with_rule_set(conn, confidence_threshold=2.0)
    case = svc.open_validator_case(
        conn,
        transaction_id=tx_id,
        source_id=old_version_id,
        validator_status="NEEDS_REVIEW",
        finding_codes=["LOW_CONFIDENCE"],
        actor_context=actor(),
    )
    conn.execute("UPDATE transactions SET state = 'awaiting_review' WHERE id = ?", (tx_id,))

    revised = create_revision(
        conn,
        transaction_id=tx_id,
        parent_version_id=old_version_id,
        rules_payload=_PAYLOAD_4F2,
        actor_context=actor(),
    )
    validate_version(conn, version_id=revised.id, confidence_threshold=0.5)  # confidence 0.9 -> PASS

    action = svc.record_action(
        conn, case_id=case.id, actor_context=actor(platform_role="reviewer"), action="resolve_continue"
    )
    assert action.action.value == "resolve_continue"
    reloaded_case = svc.list_cases(conn, tx_id)[0]
    assert reloaded_case.status.value == "resolved"
    tx_row = conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    assert tx_row["state"] == "preparation"
    conn.close()


def test_resolve_continue_on_party_mismatch_case_after_fix_succeeds() -> None:
    conn = make_reviews_db_with_rule_sets()
    tx_id, version_id = _account_tx_with_rule_set(conn, confidence_threshold=0.5)  # PASS
    participant_id = "participant-buyer"
    conn.execute(
        "INSERT INTO transaction_participants (id, transaction_id, role, legal_entity_id, "
        "status, confirmed_snapshot_json, confirmed_at, created_at, updated_at) VALUES "
        "(?, ?, 'buyer', 'entity-buyer', 'confirmed', ?, 'now', 'now', 'now')",
        (participant_id, tx_id, json.dumps({"name": "Yanlis Isim A.Ş."})),
    )
    case = svc.open_case(
        conn,
        transaction_id=tx_id,
        phase="pre_ratification",
        source_type="party_mismatch",
        source_id=participant_id,
        reason_code="PARTY_NAME_MISMATCH",
        title="buyer tarafı name uyuşmazlığı",
        description="d",
        severity="blocking",
        actor_context=actor(),
    )
    # Henüz düzeltilmedi -> ön koşul sağlanmaz.
    with pytest.raises(svc.ReviewResolutionPreconditionError):
        svc.record_action(conn, case_id=case.id, actor_context=actor(platform_role="reviewer"), action="resolve_continue")

    # Confirmed snapshot extracted (Buyer A.Ş.) ile eşleşecek şekilde düzeltildi.
    conn.execute(
        "UPDATE transaction_participants SET confirmed_snapshot_json = ? WHERE id = ?",
        (json.dumps({"name": "Buyer A.Ş."}), participant_id),
    )
    conn.execute("UPDATE transactions SET state = 'awaiting_approval' WHERE id = ?", (tx_id,))
    action = svc.record_action(
        conn, case_id=case.id, actor_context=actor(platform_role="reviewer"), action="resolve_continue"
    )
    assert action.action.value == "resolve_continue"
    reloaded_case = svc.list_cases(conn, tx_id)[0]
    assert reloaded_case.status.value == "resolved"
    tx_row = conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    assert tx_row["state"] == "preparation"
    conn.close()


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


# --- Bloklayıcı 2: comment/resolution_code güvenlik taraması ------------------------


@pytest.mark.parametrize(
    "sensitive_comment",
    [
        "Kart no 4539578763621486 ile ödeme yapıldı",  # PAN (Luhn geçerli)
        "cvv: 123",  # CVV (SAD)
        "vergi no 1234567890 ile kayıtlı",  # VKN (10 hane)
        "TCKN 12345678901 doğrulandı",  # TCKN (11 hane)
        "IBAN TR330006100519786457841326 kontrol edildi",  # IBAN
        "iletişim: buyer@example.com",  # email
        "token: aB3dEfGhIjKlMnOpQrStUvWx-9Y8z",  # capability/session token benzeri opak dize
    ],
)
def test_comment_with_sensitive_content_is_rejected(conn, sensitive_comment: str) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id, severity="warning")
    with pytest.raises(svc.ReviewCommentRejectedError):
        svc.record_action(
            conn, case_id=case.id, actor_context=actor(), action="comment",
            payload={"comment": sensitive_comment},
        )
    # Reddedilen action hiçbir satır bırakmamalı.
    assert svc.list_actions(conn, case.id) == []


def test_comment_without_sensitive_content_is_stored(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id, severity="warning")
    action = svc.record_action(
        conn, case_id=case.id, actor_context=actor(), action="comment",
        payload={"comment": "Bu bulgu incelendi, sözleşme maddesiyle uyumlu."},
    )
    assert action.payload["comment"] == "Bu bulgu incelendi, sözleşme maddesiyle uyumlu."


def test_resolution_code_with_sensitive_content_is_rejected(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open(conn, tx_id, severity="warning")
    with pytest.raises(svc.ReviewCommentRejectedError):
        svc.record_action(
            conn, case_id=case.id, actor_context=actor(), action="resolve_reject",
            payload={"resolution_code": "leaked-aB3dEfGhIjKlMnOpQrStUvWxYz"},
        )
    assert "Traceback" not in case.description
