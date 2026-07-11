"""Plan 05 / Faz 5B — `services/disputes.py` servis-katmanı testleri.

Router/HTTP yok; router-seviyesi authorization testleri `test_disputes_api.py`'dedir.
"""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.services import disputes as svc
from backend.app.services.access_control import ActorContext

_disputes_migration = import_module("backend.app.db.migrations.014_disputes")
_evidence_migration = import_module("backend.app.db.migrations.013_evidence_records")

_TX_ID = "tx-5b"
_OTHER_TX_ID = "tx-5b-other"


def _actor(user_id: str = "u-buyer", entity_id: str = "entity-buyer") -> ActorContext:
    return ActorContext(
        actor_type="user", user_id=user_id, acting_entity_id=entity_id,
        auth_method="session", request_id="req-5b",
    )


def _create_user(conn, user_id: str, email: str) -> None:
    conn.execute(
        "INSERT INTO users (id, email_normalized, password_hash, first_name, last_name, "
        "status, platform_role, created_at, updated_at) VALUES (?, ?, 'unused', 'T', 'U', "
        "'active', NULL, datetime('now'), datetime('now'))",
        (user_id, email),
    )


def _create_entity(conn, entity_id: str, created_by_user_id: str) -> None:
    conn.execute(
        "INSERT INTO legal_entities (id, entity_type, legal_name, tax_identifier_type, "
        "tax_identifier_ciphertext, tax_identifier_lookup_hmac, tax_identifier_last4, "
        "verification_status, created_by_user_id, created_at, updated_at) "
        "VALUES (?, 'company', ?, 'vkn', 'cipher', 'hmac', '1234', 'self_declared', ?, "
        "datetime('now'), datetime('now'))",
        (entity_id, f"Legal Entity {entity_id}", created_by_user_id),
    )


def _create_transaction(conn, tx_id: str, owner_entity_id: str) -> None:
    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES (?, 'awaiting_ratification', NULL, NULL, NULL, NULL, NULL, 'now', "
        "'account_v2', ?)",
        (tx_id, owner_entity_id),
    )


@pytest.fixture()
def conn(tmp_path: Path):
    connection = connect(Settings(db_path=tmp_path / "5b.db"))
    init_db(connection)
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_records'"
    ).fetchone() is None:
        _evidence_migration.apply(connection)
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='disputes'"
    ).fetchone() is None:
        _disputes_migration.apply(connection)

    _create_user(connection, "u-buyer", "buyer@example.com")
    _create_entity(connection, "entity-buyer", "u-buyer")
    _create_transaction(connection, _TX_ID, "entity-buyer")
    _create_transaction(connection, _OTHER_TX_ID, "entity-buyer")
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def _open(conn, *, milestone_id=None, reason_code="QUALITY_ISSUE", actor=None):
    return svc.open_dispute(
        conn, transaction_id=_TX_ID, milestone_id=milestone_id, reason_code=reason_code,
        description="Teslim edilen ürün sözleşmeye uygun değil.", actor_context=actor or _actor(),
    )


# --- migration smoke -----------------------------------------------------------------


def test_migration_is_additive_and_rerun_safe(tmp_path: Path) -> None:
    connection = connect(Settings(db_path=tmp_path / "smoke.db"))
    init_db(connection)
    init_db(connection)
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='disputes'"
    ).fetchone() is not None
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='disputes'"
    ).fetchone()
    assert row is not None
    with pytest.raises(Exception):
        _disputes_migration.apply(connection)
    connection.close()


def test_dispute_actions_append_only(conn) -> None:
    dispute = _open(conn)
    svc.record_dispute_action(conn, dispute_id=dispute.id, actor_context=_actor(), action="comment",
                               payload={"comment": "not"})
    action_id = svc.list_dispute_actions(conn, dispute.id)[0].id
    with pytest.raises(Exception):
        conn.execute("UPDATE dispute_actions SET action = 'cancel' WHERE id = ?", (action_id,))
    with pytest.raises(Exception):
        conn.execute("DELETE FROM dispute_actions WHERE id = ?", (action_id,))


# --- open_dispute ----------------------------------------------------------------------


def test_actor_user_and_entity_are_recorded(conn) -> None:
    dispute = _open(conn, actor=_actor("u-buyer", "entity-buyer"))
    assert dispute.opened_by_user_id == "u-buyer"
    assert dispute.opened_by_entity_id == "entity-buyer"


def test_system_actor_cannot_open_dispute(conn) -> None:
    with pytest.raises(svc.DisputeAuthorizationError):
        svc.open_dispute(
            conn, transaction_id=_TX_ID, milestone_id=None, reason_code="QUALITY_ISSUE",
            description="d", actor_context=ActorContext(actor_type="anonymous"),
        )


def test_second_open_dispute_in_same_scope_is_rejected(conn) -> None:
    _open(conn)
    with pytest.raises(svc.DisputeAlreadyOpenError):
        _open(conn)


def test_transaction_wide_dispute_blocks_every_milestone(conn) -> None:
    _open(conn, milestone_id=None)
    assert svc.has_open_dispute(conn, _TX_ID, milestone_id=None) is True
    assert svc.has_open_dispute(conn, _TX_ID, milestone_id="m-1") is True
    assert svc.has_open_dispute(conn, _TX_ID, milestone_id="m-2") is True


def test_milestone_dispute_blocks_only_that_milestone(conn) -> None:
    _open(conn, milestone_id="m-1")
    assert svc.has_open_dispute(conn, _TX_ID, milestone_id="m-1") is True
    assert svc.has_open_dispute(conn, _TX_ID, milestone_id="m-2") is False


def test_resolved_and_cancelled_disputes_do_not_block(conn) -> None:
    dispute = _open(conn, milestone_id="m-1")
    svc.record_dispute_action(conn, dispute_id=dispute.id, actor_context=_actor(), action="resolve",
                               payload={"resolution_code": "SETTLED"})
    assert svc.has_open_dispute(conn, _TX_ID, milestone_id="m-1") is False

    dispute2 = _open(conn, milestone_id="m-2")
    svc.record_dispute_action(conn, dispute_id=dispute2.id, actor_context=_actor(), action="cancel")
    assert svc.has_open_dispute(conn, _TX_ID, milestone_id="m-2") is False


# --- actions -------------------------------------------------------------------------


def test_cancel_only_by_opener(conn) -> None:
    dispute = _open(conn, actor=_actor("u-buyer", "entity-buyer"))
    with pytest.raises(svc.DisputeAuthorizationError):
        svc.record_dispute_action(
            conn, dispute_id=dispute.id, actor_context=_actor("u-other", "entity-buyer"), action="cancel"
        )


def test_state_changing_action_on_resolved_dispute_is_rejected(conn) -> None:
    dispute = _open(conn)
    svc.record_dispute_action(conn, dispute_id=dispute.id, actor_context=_actor(), action="resolve",
                               payload={"resolution_code": "SETTLED"})
    with pytest.raises(svc.DisputeClosedError):
        svc.record_dispute_action(conn, dispute_id=dispute.id, actor_context=_actor(), action="comment",
                                   payload={"comment": "too late"})


def test_cross_transaction_evidence_attach_is_rejected(conn) -> None:
    from backend.app.services import evidence_records as evidence_svc

    other_evidence = evidence_svc.submit_evidence(
        conn, transaction_id=_OTHER_TX_ID, milestone_id=None, evidence_type="e_irsaliye",
        source="external_api", actor_context=_actor(), payload={"delivered_quantity": 1.0},
        verification_status="verified", external_reference="other-ref",
    )
    dispute = _open(conn)
    with pytest.raises(svc.DisputeCrossTransactionReferenceError):
        svc.record_dispute_action(
            conn, dispute_id=dispute.id, actor_context=_actor(), action="attach_evidence",
            evidence_id=other_evidence.id,
        )


def test_same_transaction_evidence_attach_succeeds(conn) -> None:
    from backend.app.services import evidence_records as evidence_svc

    own_evidence = evidence_svc.submit_evidence(
        conn, transaction_id=_TX_ID, milestone_id=None, evidence_type="e_irsaliye",
        source="external_api", actor_context=_actor(), payload={"delivered_quantity": 1.0},
        verification_status="verified", external_reference="own-ref",
    )
    dispute = _open(conn)
    action = svc.record_dispute_action(
        conn, dispute_id=dispute.id, actor_context=_actor(), action="attach_evidence",
        evidence_id=own_evidence.id,
    )
    assert action.evidence_id == own_evidence.id


def test_escalate_dispute_without_human_review_case_call_never_happens(conn) -> None:
    """Review case/video anomaly kendi başına dispute action üretmez -- bu
    modülde escalate_dispute'u tetikleyen tek yol, açık `record_dispute_action`
    çağrısıdır (endpoint'i çağıran yetkili participant approver)."""
    dispute = _open(conn)
    with pytest.raises(ValueError):
        svc.record_dispute_action(
            conn, dispute_id=dispute.id, actor_context=_actor(), action="escalate_dispute",
        )  # review_case_id verilmeden escalate edilemez


def test_escalate_dispute_cross_transaction_review_case_is_rejected(conn) -> None:
    from backend.app.services import review as review_service

    other_case = review_service.open_case(
        conn, transaction_id=_OTHER_TX_ID, phase="pre_ratification", source_type="system",
        source_id=None, reason_code="MANUAL_HOLD", title="t", description="d", severity="warning",
        actor_context=_actor(),
    )
    dispute = _open(conn)
    with pytest.raises(svc.DisputeCrossTransactionReferenceError):
        svc.record_dispute_action(
            conn, dispute_id=dispute.id, actor_context=_actor(), action="escalate_dispute",
            payload={"review_case_id": other_case.id},
        )


def test_escalate_dispute_same_transaction_review_case_succeeds(conn) -> None:
    from backend.app.services import review as review_service

    case = review_service.open_case(
        conn, transaction_id=_TX_ID, phase="pre_ratification", source_type="system",
        source_id=None, reason_code="MANUAL_HOLD", title="t", description="d", severity="warning",
        actor_context=_actor(),
    )
    dispute = _open(conn)
    action = svc.record_dispute_action(
        conn, dispute_id=dispute.id, actor_context=_actor(), action="escalate_dispute",
        payload={"review_case_id": case.id},
    )
    assert action.payload["review_case_id"] == case.id
    reloaded = svc.get_dispute(conn, dispute.id)
    assert reloaded.status == "under_review"


# --- content safety --------------------------------------------------------------------


@pytest.mark.parametrize(
    "sensitive_comment",
    [
        "kart no 4539578763621486 ile ödendi",
        "iletişim buyer@example.com",
        "token: aB3dEfGhIjKlMnOpQrStUvWx-9Y8z",
    ],
)
def test_comment_with_sensitive_content_is_rejected(conn, sensitive_comment: str) -> None:
    dispute = _open(conn)
    with pytest.raises(svc.DisputeContentRejectedError):
        svc.record_dispute_action(
            conn, dispute_id=dispute.id, actor_context=_actor(), action="comment",
            payload={"comment": sensitive_comment},
        )


def test_description_with_sensitive_content_is_rejected(conn) -> None:
    with pytest.raises(svc.DisputeContentRejectedError):
        svc.open_dispute(
            conn, transaction_id=_TX_ID, milestone_id=None, reason_code="QUALITY_ISSUE",
            description="Buyer email adresi buyer@example.com ile iletişime geçildi.",
            actor_context=_actor(),
        )


def test_reason_code_must_be_upper_snake_case(conn) -> None:
    with pytest.raises(svc.DisputeContentRejectedError):
        svc.open_dispute(
            conn, transaction_id=_TX_ID, milestone_id=None, reason_code="quality-issue",
            description="d", actor_context=_actor(),
        )


# --- isolation ---------------------------------------------------------------------------


def test_disputes_module_imports_no_payment_provider() -> None:
    module_path = (
        Path(__file__).resolve().parents[1] / "backend" / "app" / "services" / "disputes.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    forbidden_prefixes = (
        "backend.app.services.payment_provider",
        "backend.app.services.payments.moka",
        "backend.app.services.payments.ports",
        "fastapi",
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in imported:
        assert not any(name == p or name.startswith(p + ".") for p in forbidden_prefixes), name
