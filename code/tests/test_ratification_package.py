"""Plan 04 / Wave B / Faz 4D ratification package + coordinator testleri."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.repositories import packages as packages_repo
from backend.app.schemas.payments import (
    FundingScheduleSpec,
    MilestoneReleaseOverride,
    RequestedReleaseMode,
)
from backend.app.services import participants as participants_service
from backend.app.services import ratification_package as package_service
from backend.app.services.access_control import ActorContext
from backend.app.services.payments.domain import MOKA_STANDARD_PROFILE
from backend.app.services.payments.funding_coordinator import ensure_pool_funded
from backend.app.services.rule_versions import (
    create_initial_from_extraction,
    create_revision,
    validate_version,
)
from backend.app.services.tracking_policy import create_draft_policy


_PAYLOAD = {
    "contract_id": "contract-4d",
    "parties": {
        "buyer": {"name": "Buyer A.Ş.", "tax_id": "1234567890"},
        "seller": {"name": "Seller Ltd.", "tax_id": "9876543210"},
    },
    "commercial_terms": {
        "currency": "TRY",
        "total_amount": 100.0,
        "goods": [{"name": "Pompa", "quantity": 10.0, "unit": "adet"}],
        "delivery_deadline": "2026-09-01",
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


def _actor() -> ActorContext:
    return ActorContext(
        actor_type="user",
        user_id="u-buyer",
        acting_entity_id="entity-buyer",
        auth_method="session",
        request_id="req-4d",
    )


@pytest.fixture()
def ready_conn(tmp_path: Path):
    conn = connect(Settings(db_path=tmp_path / "4d.db"))
    init_db(conn)
    tx_id = "tx-4d"
    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES (?, 'awaiting_ratification', NULL, NULL, NULL, NULL, NULL, 'now', 'account_v2', ?)",
        (tx_id, "entity-buyer"),
    )
    create_draft_policy(conn, tx_id)
    conn.execute(
        "UPDATE tracking_policies SET manager_physical_delivery_confirmed = 1, "
        "tracking_mode = 'off', status = 'locked', locked_at = 'now' WHERE transaction_id = ?",
        (tx_id,),
    )

    participants_service.attach_creator(conn, tx_id, _actor(), "buyer", "entity-buyer")
    participants_service.create_counterparty_placeholder(conn, tx_id, "seller", None)
    participants = {
        row["role"]: row
        for row in conn.execute(
            "SELECT * FROM transaction_participants WHERE transaction_id = ?", (tx_id,)
        ).fetchall()
    }
    for role, entity_id, snapshot in (
        ("buyer", "entity-buyer", {"name": "Buyer A.Ş.", "tax_id": "1234567890"}),
        ("seller", "entity-seller", {"name": "Seller Ltd.", "tax_id": "9876543210"}),
    ):
        conn.execute(
            "UPDATE transaction_participants SET legal_entity_id = ?, status = 'confirmed', "
            "confirmed_snapshot_json = ?, confirmed_at = 'now', updated_at = 'now' WHERE id = ?",
            (entity_id, json.dumps(snapshot), participants[role]["id"]),
        )

    document_id = "doc-4d"
    run_id = "run-4d"
    conn.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) VALUES (?, ?, 1, 'contract.md', "
        "'tx-4d/doc-4d', 'document-hash', 'active', 'now')",
        (document_id, tx_id),
    )
    conn.execute(
        "INSERT INTO extraction_runs (id, transaction_id, document_id, provider, model, "
        "prompt_version, schema_version, extraction_json, status, created_at) "
        "VALUES (?, ?, ?, 'fake', 'fake-v1', 'v1', 'v1', ?, 'ok', 'now')",
        (run_id, tx_id, document_id, json.dumps(_PAYLOAD)),
    )
    version = create_initial_from_extraction(
        conn, transaction_id=tx_id, extraction_run_id=run_id, rules_payload=_PAYLOAD
    )
    validate_version(conn, version_id=version.id, confidence_threshold=0.7)
    conn.commit()
    yield conn, tx_id
    conn.close()


def _build(conn, tx_id: str):
    return package_service.build_current_package(
        conn,
        transaction_id=tx_id,
        funding_schedule_spec=FundingScheduleSpec(),
        capabilities=MOKA_STANDARD_PROFILE,
        actor_context=_actor(),
    )


def test_canonical_package_json_is_stable_and_rejects_float() -> None:
    left = package_service.canonical_package_json({"b": 2, "a": "ç"})
    right = package_service.canonical_package_json({"a": "ç", "b": 2})
    assert left == right
    assert package_service.compute_package_hash(left) == package_service.compute_package_hash(right)
    with pytest.raises(ValueError):
        package_service.canonical_package_json({"amount": 1.5})


def test_build_package_is_ready_canonical_and_idempotent(ready_conn) -> None:
    conn, tx_id = ready_conn
    package = _build(conn, tx_id)
    repeated = _build(conn, tx_id)
    payload = json.loads(package.canonical_payload_json)

    assert package.id == repeated.id
    assert package.version == 1
    assert package.status.value == "draft"
    assert package_service.verify_integrity(package) is True
    assert package.package_hash == hashlib.sha256(
        package.canonical_payload_json.encode("utf-8")
    ).hexdigest()
    assert "1234567890" not in package.canonical_payload_json
    assert payload["funding_schedule"]["total_amount_minor"] == 10000
    assert payload["commercial_summary"]["goods"][0]["quantity"] == "10"


def test_open_package_is_idempotent_and_integrity_failure_is_rejected(ready_conn) -> None:
    conn, tx_id = ready_conn
    package = _build(conn, tx_id)
    opened = package_service.open_package(conn, package_id=package.id, actor_context=_actor())
    repeated = package_service.open_package(conn, package_id=package.id, actor_context=_actor())

    assert opened.status.value == "open"
    assert repeated.status.value == "open"
    tampered = package.model_copy(update={"package_hash": "0" * 64})
    assert package_service.verify_integrity(tampered) is False


def test_open_package_transitions_account_state_to_awaiting_ratification(ready_conn) -> None:
    """Major 1 remediation: gerçek PASS-sonrası state (`awaiting_approval`) --
    ki pipeline validator PASS'ta transaction'ı buraya bırakır -- package open
    olunca stratejik kontrattaki `awaiting_ratification`'a geçmeli (önceden bu
    geçiş hiç yapılmıyordu, FundingCoordinator `awaiting_approval`'dan
    doğrudan `funding_pending`'e atlıyordu)."""
    conn, tx_id = ready_conn
    conn.execute("UPDATE transactions SET state = 'awaiting_approval' WHERE id = ?", (tx_id,))
    package = _build(conn, tx_id)
    package_service.open_package(conn, package_id=package.id, actor_context=_actor())
    tx_row = conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    assert tx_row["state"] == "awaiting_ratification"


def test_package_bound_inputs_are_db_immutable(ready_conn) -> None:
    conn, tx_id = ready_conn
    package = _build(conn, tx_id)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE ratification_packages SET canonical_payload_json = '{}' WHERE id = ?",
            (package.id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM ratification_packages WHERE id = ?", (package.id,))


def test_rule_revision_and_schedule_change_supersede_current_package(ready_conn) -> None:
    conn, tx_id = ready_conn
    first = _build(conn, tx_id)
    current_rule = conn.execute(
        "SELECT id FROM rule_set_versions WHERE transaction_id = ? ORDER BY version DESC LIMIT 1",
        (tx_id,),
    ).fetchone()[0]
    revised_payload = json.loads(json.dumps(_PAYLOAD))
    revised_payload["contract_id"] = "contract-4d-revision"
    revision = create_revision(
        conn,
        transaction_id=tx_id,
        parent_version_id=current_rule,
        rules_payload=revised_payload,
        actor_context=_actor(),
    )
    validate_version(conn, version_id=revision.id, confidence_threshold=0.7)
    second = package_service.supersede_if_inputs_changed(
        conn,
        transaction_id=tx_id,
        funding_schedule_spec=FundingScheduleSpec(
            overrides=(
                MilestoneReleaseOverride(
                    rule_index=0,
                    release_mode=RequestedReleaseMode.FIXED_TRANCHES,
                    tranche_count=2,
                ),
            )
        ),
        capabilities=MOKA_STANDARD_PROFILE,
        actor_context=_actor(),
    )

    assert second.id != first.id
    assert second.version == 2
    assert second.rule_set_version_id == revision.id


def test_incomplete_readiness_and_legacy_transaction_are_rejected(ready_conn) -> None:
    conn, tx_id = ready_conn
    conn.execute(
        "UPDATE tracking_policies SET status = 'draft', locked_at = NULL WHERE transaction_id = ?",
        (tx_id,),
    )
    with pytest.raises(package_service.PackageNotReadyError) as missing_policy:
        _build(conn, tx_id)
    assert missing_policy.value.reason_code == "TRACKING_POLICY_NOT_LOCKED"

    conn.execute("UPDATE transactions SET lifecycle_version = 'legacy_v1' WHERE id = ?", (tx_id,))
    with pytest.raises(package_service.PackageConflictError) as legacy:
        _build(conn, tx_id)
    assert legacy.value.reason_code == "LEGACY_TRANSACTION"


def test_policy_change_supersedes_current_package(ready_conn) -> None:
    conn, tx_id = ready_conn
    first = _build(conn, tx_id)
    conn.execute(
        "UPDATE tracking_policies SET tracking_mode = 'document_only' WHERE transaction_id = ?",
        (tx_id,),
    )
    second = package_service.supersede_if_inputs_changed(
        conn,
        transaction_id=tx_id,
        funding_schedule_spec=FundingScheduleSpec(),
        capabilities=MOKA_STANDARD_PROFILE,
        actor_context=_actor(),
    )

    assert second.id != first.id
    assert second.version == 2
    assert conn.execute(
        "SELECT status FROM ratification_packages WHERE id = ?", (first.id,)
    ).fetchone()[0] == "superseded"


def test_complete_package_funds_units_and_activates_once(ready_conn) -> None:
    # Plan 06A cutover: çift ratification sonrası paket artık funding_pending'de
    # durmaz -- funding unit'ler pool'lanır ve transaction active olur, funding
    # exactly-once (replay yeni provider call/event üretmez).
    conn, tx_id = ready_conn
    package = _build(conn, tx_id)
    package_service.open_package(conn, package_id=package.id, actor_context=_actor())
    packages_repo.mark_complete(conn, package_id=package.id, completed_at="now")

    first = ensure_pool_funded(conn, tx_id, package.id, _actor())
    second = ensure_pool_funded(conn, tx_id, package.id, _actor())
    funding_required_count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE transaction_id = ? AND event_type = 'funding_required'",
        (tx_id,),
    ).fetchone()[0]
    pool_created_count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE transaction_id = ? "
        "AND event_type = 'funding_units_pool_created'",
        (tx_id,),
    ).fetchone()[0]
    unit_count = conn.execute(
        "SELECT COUNT(*) FROM funding_units WHERE transaction_id = ?", (tx_id,)
    ).fetchone()[0]
    provider_payment_count = conn.execute(
        "SELECT COUNT(*) FROM provider_payments WHERE funding_unit_id IN "
        "(SELECT id FROM funding_units WHERE transaction_id = ?)",
        (tx_id,),
    ).fetchone()[0]

    assert first.status == second.status == "active"
    assert first.event_emitted is True
    assert second.event_emitted is False
    assert funding_required_count == 1
    assert pool_created_count == 1
    assert unit_count >= 1
    # Funding exactly-once: replay ikinci provider payment üretmez.
    assert provider_payment_count == unit_count
    assert conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()[0] == "active"
