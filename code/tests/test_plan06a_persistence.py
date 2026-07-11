"""Plan 06A early branch: migration, schedule materialization, fake funding."""

from __future__ import annotations

import json
from importlib import import_module

import pytest

from backend.app.db import connect, init_db
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from backend.app.services.payments import funding_coordinator
from backend.app.services.payments.domain import (
    CreatePoolPaymentResult,
    PaymentDetailResult,
    ProviderOperationOutcome,
    ProviderPaymentDetail,
    ProviderPaymentIdentifier,
    ProviderPaymentStatus,
)
from backend.app.services.payments.ports import FakePaymentGateway, InMemoryPaymentStore
from backend.app.services.ratification_package import canonical_package_json, compute_package_hash


def _apply_6a(conn) -> None:
    for name in (
        "015_milestones",
        "016_funding_units_provider_payments",
        "017_release_instructions",
    ):
        table_name = {
            "015_milestones": "milestones",
            "016_funding_units_provider_payments": "funding_units",
            "017_release_instructions": "release_instructions",
        }[name]
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        ).fetchone()
        if exists is None:
            import_module(f"backend.app.db.migrations.{name}").apply(conn)


def _seed_complete_package(conn) -> tuple[str, str]:
    tx_id = "tx-6a-demo"
    package_id = "package-6a-demo"
    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES (?, 'funding_pending', NULL, NULL, NULL, NULL, NULL, 'now', 'account_v2', 'entity')",
        (tx_id,),
    )
    conn.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) VALUES ('doc-6a', ?, 1, 'x.md', "
        "'tx-6a/doc', 'doc-hash', 'active', 'now')",
        (tx_id,),
    )
    conn.execute(
        "INSERT INTO rule_set_versions (id, transaction_id, version, rules_json, rules_hash, "
        "status, validator_status, created_by_actor_type, created_at) VALUES "
        "('rule-6a', ?, 1, '{}', 'rule-hash', 'ratifiable', 'PASS', 'system', 'now')",
        (tx_id,),
    )
    payload = {
        "provider_profile": "moka_standard_v1",
        "rule_set": {"id": "rule-6a"},
        "funding_schedule": {
            "total_amount_minor": 1000,
            "milestones": [
                {
                    "rule_index": 0,
                    "title": "Teslimat",
                    "trigger_type": "delivery",
                    "basis_points": 10000,
                    "amount_minor": 1000,
                    "currency": "TRY",
                    "required_evidence": ["e_irsaliye"],
                    "release_mode": "fixed_tranches",
                    "funding_units": [
                        {
                            "sequence": 1,
                            "amount_minor": 600,
                            "eligibility_type": "verified_quantity",
                            "eligibility_payload": {"quantity_threshold": 6},
                        },
                        {
                            "sequence": 2,
                            "amount_minor": 400,
                            "eligibility_type": "verified_quantity",
                            "eligibility_payload": {"quantity_threshold": 10},
                        },
                    ],
                }
            ],
        },
    }
    canonical = canonical_package_json(payload)
    conn.execute(
        """INSERT INTO ratification_packages (
            id, transaction_id, version, document_id, rule_set_version_id,
            tracking_policy_version_id, canonical_payload_json, document_hash,
            rule_set_hash, participant_snapshot_hash, tracking_policy_hash,
            package_hash, status, created_at, opened_at, completed_at
        ) VALUES (?, ?, 1, 'doc-6a', 'rule-6a', NULL, ?, 'doc-hash', 'rule-hash',
                  'participant-hash', 'policy-hash', ?, 'complete', 'now', 'now', 'now')""",
        (package_id, tx_id, canonical, compute_package_hash(canonical)),
    )
    conn.commit()
    return tx_id, package_id


def _system_actor() -> ActorContext:
    return ActorContext(actor_type="anonymous", auth_method="none")


def test_6a_materializes_schedule_and_funds_each_unit_once(monkeypatch) -> None:
    conn = connect()
    init_db(conn)
    _apply_6a(conn)
    tx_id, package_id = _seed_complete_package(conn)

    result = funding_coordinator.ensure_pool_funded(
        conn, tx_id, package_id, _system_actor()
    )
    assert result.status == "active"
    units = funding_units_repo.list_for_transaction(conn, tx_id)
    assert [unit["other_trx_code"] for unit in units] == [
        "M4T-tx6ademo-P1-U01",
        "M4T-tx6ademo-P1-U02",
    ]
    assert [unit["status"] for unit in units] == ["pool_created", "pool_created"]
    assert conn.execute("SELECT COUNT(*) FROM milestones").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM provider_payments").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM provider_operations").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM fake_provider_payments").fetchone()[0] == 2
    assert conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()[0] == "active"

    second = funding_coordinator.ensure_pool_funded(
        conn, tx_id, package_id, _system_actor()
    )
    assert second.status == "active"
    assert second.event_emitted is False
    assert conn.execute("SELECT COUNT(*) FROM provider_payments").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM provider_operations").fetchone()[0] == 2
    # funding_required + funding_units_pool_created exactly-once.
    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'funding_required'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'funding_units_pool_created'"
    ).fetchone()[0] == 1
    conn.close()


class _FailingUnitGateway:
    """Bir belirli other_trx_code'u kalıcı (definitive) reddeden fake gateway."""

    def __init__(self, fail_other_trx_code: str) -> None:
        self._fail = fail_other_trx_code
        self._inner = FakePaymentGateway()
        self.create_calls = 0

    def create_pool_payment(self, command):
        self.create_calls += 1
        if command.other_trx_code == self._fail:
            return CreatePoolPaymentResult(
                outcome=ProviderOperationOutcome.FAILED,
                provider_code="BANK_DECLINE",
                message="Definitive decline.",
            )
        return self._inner.create_pool_payment(command)

    def approve_pool_payment(self, identifier):
        return self._inner.approve_pool_payment(identifier)

    def undo_pool_approval(self, identifier):
        return self._inner.undo_pool_approval(identifier)

    def get_payment_detail(self, query):
        return self._inner.get_payment_detail(query)


class _UnknownThenPooledGateway:
    """Create timeout (unknown) döner ama ödeme aslında pool olarak oluşmuştur."""

    def __init__(self) -> None:
        self._store = InMemoryPaymentStore()
        self.create_calls = 0

    def create_pool_payment(self, command):
        self.create_calls += 1
        identifier = ProviderPaymentIdentifier(
            virtual_pos_order_id=f"VPOS-{command.other_trx_code}",
            other_trx_code=command.other_trx_code,
        )
        self._store.save(
            ProviderPaymentDetail(
                identifier=identifier,
                amount_minor=command.amount_minor,
                currency=command.currency,
                status=ProviderPaymentStatus.POOL,
            )
        )
        return CreatePoolPaymentResult(
            outcome=ProviderOperationOutcome.UNKNOWN,
            provider_code="TRANSPORT_TIMEOUT",
            message="Sonuç belirsiz.",
        )

    def approve_pool_payment(self, identifier):  # pragma: no cover - kullanılmaz
        raise NotImplementedError

    def undo_pool_approval(self, identifier):  # pragma: no cover - kullanılmaz
        raise NotImplementedError

    def get_payment_detail(self, query):
        payment = self._store.get(query.identifier)
        if payment is None:
            return PaymentDetailResult(
                outcome=ProviderOperationOutcome.FAILED,
                provider_code="PROVIDER_PAYMENT_NOT_FOUND",
                message="Bulunamadı.",
            )
        return PaymentDetailResult(
            outcome=ProviderOperationOutcome.SUCCESS, payment=payment
        )


def test_6a_schedule_drift_fails_closed() -> None:
    conn = connect()
    init_db(conn)
    tx_id, package_id = _seed_complete_package(conn)
    funding_coordinator.persist_funding_schedule(conn, tx_id, package_id)

    # Persist edilmiş unit tutarını package payload'ından saptır -> fail closed.
    conn.execute(
        "UPDATE funding_units SET amount_minor = amount_minor + 1 WHERE sequence = 1"
    )
    with pytest.raises(funding_coordinator.FundingCoordinatorError):
        funding_coordinator.persist_funding_schedule(conn, tx_id, package_id)
    conn.close()


def test_6a_partial_pool_failure_holds_funding_pending_with_blocking_review() -> None:
    conn = connect()
    init_db(conn)
    tx_id, package_id = _seed_complete_package(conn)
    gateway = _FailingUnitGateway("M4T-tx6ademo-P1-U02")

    result = funding_coordinator.ensure_pool_funded(
        conn, tx_id, package_id, _system_actor(), gateway=gateway
    )

    assert result.status == "funding_pending"
    assert conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()[0] == "funding_pending"
    statuses = {
        unit["sequence"]: unit["status"]
        for unit in funding_units_repo.list_for_transaction(conn, tx_id)
    }
    # Kısmi başarı satırları korunur: U01 pool_created, U02 definitive failed.
    assert statuses[1] == "pool_created"
    assert statuses[2] == "pool_creation_failed"
    assert review_service.has_blocking_case(conn, tx_id, phase="payment") is True
    conn.close()


def test_6a_create_unknown_reconciles_without_blind_retry() -> None:
    conn = connect()
    init_db(conn)
    tx_id, package_id = _seed_complete_package(conn)
    gateway = _UnknownThenPooledGateway()

    first = funding_coordinator.ensure_pool_funded(
        conn, tx_id, package_id, _system_actor(), gateway=gateway
    )
    assert first.status == "funding_pending"
    assert gateway.create_calls == 2  # her unit için bir kez
    unknown_units = {
        unit["status"]
        for unit in funding_units_repo.list_for_transaction(conn, tx_id)
    }
    assert unknown_units == {"pool_creation_unknown"}

    second = funding_coordinator.ensure_pool_funded(
        conn, tx_id, package_id, _system_actor(), gateway=gateway
    )
    # Reconcile detail üzerinden yürür; kör create retry YOK.
    assert second.status == "active"
    assert gateway.create_calls == 2
    assert all(
        unit["status"] == "pool_created"
        for unit in funding_units_repo.list_for_transaction(conn, tx_id)
    )
    conn.close()


def test_6a_new_package_version_uses_new_other_trx_code() -> None:
    conn = connect()
    init_db(conn)
    tx_id, package_id = _seed_complete_package(conn)
    funding_coordinator.persist_funding_schedule(conn, tx_id, package_id)

    # v1'i supersede edip tek unitlik v2 package'ı complete olarak ekle.
    conn.execute(
        "UPDATE ratification_packages SET status = 'superseded' WHERE id = ?",
        (package_id,),
    )
    payload_v2 = {
        "provider_profile": "moka_standard_v1",
        "rule_set": {"id": "rule-6a"},
        "funding_schedule": {
            "total_amount_minor": 1000,
            "milestones": [
                {
                    "rule_index": 0,
                    "title": "Teslimat",
                    "trigger_type": "delivery",
                    "basis_points": 10000,
                    "amount_minor": 1000,
                    "currency": "TRY",
                    "required_evidence": ["e_irsaliye"],
                    "release_mode": "all_or_nothing",
                    "funding_units": [
                        {
                            "sequence": 1,
                            "amount_minor": 1000,
                            "eligibility_type": "milestone_completion",
                            "eligibility_payload": {},
                        }
                    ],
                }
            ],
        },
    }
    canonical_v2 = canonical_package_json(payload_v2)
    conn.execute(
        """INSERT INTO ratification_packages (
            id, transaction_id, version, document_id, rule_set_version_id,
            tracking_policy_version_id, canonical_payload_json, document_hash,
            rule_set_hash, participant_snapshot_hash, tracking_policy_hash,
            package_hash, status, created_at, opened_at, completed_at
        ) VALUES ('package-6a-v2', ?, 2, 'doc-6a', 'rule-6a', NULL, ?, 'doc-hash',
                  'rule-hash', 'participant-hash', 'policy-hash', ?, 'complete', 'now',
                  'now', 'now')""",
        (tx_id, canonical_v2, compute_package_hash(canonical_v2)),
    )
    conn.commit()

    funding_coordinator.persist_funding_schedule(conn, tx_id, "package-6a-v2")

    codes = {
        unit["ratification_package_id"]: unit["other_trx_code"]
        for unit in funding_units_repo.list_for_transaction(conn, tx_id)
    }
    # v1 P1 unit'leri korunur; v2 kendi P2 OtherTrxCode'unu üretir, karışmaz.
    assert codes[package_id] in {"M4T-tx6ademo-P1-U01", "M4T-tx6ademo-P1-U02"}
    assert codes["package-6a-v2"] == "M4T-tx6ademo-P2-U01"
    conn.close()
