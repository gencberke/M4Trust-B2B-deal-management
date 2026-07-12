"""Faz 6C — account settlement cutover + ReleaseCoordinator testleri.

Gerçek funded account seed'i `test_ratifications._setup_open_package` +
çift ratification (ensure_pool_funded fake gateway ile funding unit'leri pool'lar)
üzerinden kurulur; böylece settlement account yolu persisted milestone/funding
unit + evidence üzerinden çalışır (legacy approvals tablosu KULLANILMAZ).
"""

from __future__ import annotations

import json

import pytest

from backend.app.config import Settings
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.services import disputes as disputes_service
from backend.app.services import evidence_records as evidence_service
from backend.app.services import ratifications as ratifications_service
from backend.app.services import review as review_service
from backend.app.services import settlement
from backend.app.services.access_control import ActorContext
from backend.app.services.payments.ports import FakePaymentGateway
from backend.app.services.payments.ports import InMemoryPaymentStore
from backend.app.services.payments.domain import (
    ProviderOperationOutcome,
    ProviderOperationResult,
    ProviderPaymentIdentifier,
)
from backend.app.repositories import participants as participants_repo
from backend.app.schemas.payments import (
    FundingScheduleSpec,
    MilestoneReleaseOverride,
    RequestedReleaseMode,
)
from backend.app.services import participants as participants_service
from backend.app.services import ratification_package as package_service
from backend.app.services.payments.domain import MOKA_STANDARD_PROFILE
from backend.app.services.rule_versions import (
    create_initial_from_extraction,
    validate_version,
)
from backend.app.repositories.provider_payments import SQLitePaymentStore
from backend.app.services.tracking_policy import create_draft_policy
from reviews_fixtures import create_real_session, create_real_user
from test_ratifications import _PAYLOAD, _actor, _setup_open_package, make_db


def _settings(tmp_path) -> Settings:
    return Settings(db_path=tmp_path / "6c.db")


def _create_entity(conn, entity_id: str, user_id: str) -> None:
    conn.execute(
        "INSERT INTO legal_entities (id, entity_type, legal_name, tax_identifier_type, "
        "tax_identifier_ciphertext, tax_identifier_lookup_hmac, tax_identifier_last4, "
        "verification_status, created_by_user_id, created_at, updated_at) "
        "VALUES (?, 'company', ?, 'vkn', 'cipher', ?, '1234', 'self_declared', ?, 'now', 'now')",
        (entity_id, entity_id, entity_id, user_id),
    )


def _ratify_both(conn, package_id: str) -> None:
    ratifications_service.create_ratification(
        conn, package_id=package_id, actor_context=_actor("u-buyer", "entity-buyer"),
        auth_method="session",
    )
    ratifications_service.create_ratification(
        conn, package_id=package_id, actor_context=_actor("u-seller", "entity-seller"),
        auth_method="session",
    )
    conn.commit()


def _add_membership(conn, membership_id: str, user_id: str, entity_id: str) -> None:
    conn.execute(
        "INSERT INTO memberships (id, user_id, legal_entity_id, role, status, created_at) "
        "VALUES (?, ?, ?, 'member', 'active', 'now')",
        (membership_id, user_id, entity_id),
    )


def _seed_funded_account(tmp_path, tx_id: str = "tx-6c"):
    conn = make_db(tmp_path / "6c.db")
    create_real_user(conn, email_normalized="6c-buyer@example.com", user_id="u-buyer")
    create_real_user(conn, email_normalized="6c-seller@example.com", user_id="u-seller")
    _create_entity(conn, "entity-buyer", "u-buyer")
    _create_entity(conn, "entity-seller", "u-seller")
    _add_membership(conn, "m-6c-buyer", "u-buyer", "entity-buyer")
    _add_membership(conn, "m-6c-seller", "u-seller", "entity-seller")
    package_id = _setup_open_package(conn, tx_id)
    _ratify_both(conn, package_id)
    # Çift ratification funding'i tetikler; account active + unit'ler pool_created.
    assert conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()[0] == "active"
    return conn, tx_id, package_id


def _seed_fixed_tranche_account(tmp_path, tx_id: str = "tx-6c-tranche", *, tranche_count: int = 4):
    """100 birim teslim / N tranche fixed-tranches funded account (Moka §3.5)."""

    conn = make_db(tmp_path / "6c.db")
    create_real_user(conn, email_normalized="6c-buyer@example.com", user_id="u-buyer")
    create_real_user(conn, email_normalized="6c-seller@example.com", user_id="u-seller")
    _create_entity(conn, "entity-buyer", "u-buyer")
    _create_entity(conn, "entity-seller", "u-seller")

    payload = json.loads(json.dumps(_PAYLOAD))
    payload["commercial_terms"]["goods"][0]["quantity"] = 100.0
    # trigger evaluator kararını etkilemez; teslim-gate'i required_evidence sağlar.
    payload["payment_rules"][0]["required_evidence"] = ["e_irsaliye"]

    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES (?, 'awaiting_ratification', NULL, NULL, NULL, NULL, NULL, 'now', 'account_v2', ?)",
        (tx_id, "entity-buyer"),
    )
    create_draft_policy(conn, tx_id)
    conn.execute(
        "UPDATE tracking_policies SET manager_physical_delivery_confirmed = 1, "
        "tracking_mode = 'document_only', status = 'locked', locked_at = 'now' "
        "WHERE transaction_id = ?",
        (tx_id,),
    )
    participants_service.attach_creator(conn, tx_id, _actor("u-buyer", "entity-buyer"), "buyer", "entity-buyer")
    participants_service.create_counterparty_placeholder(conn, tx_id, "seller", None)
    rows = {
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
            (entity_id, json.dumps(snapshot), rows[role]["id"]),
        )
    participants_repo.create_assignment(
        conn, transaction_id=tx_id, participant_id=rows["seller"]["id"],
        user_id="u-seller", legal_entity_id="entity-seller", role="manager",
    )

    document_id, run_id = f"doc-{tx_id}", f"run-{tx_id}"
    conn.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) VALUES (?, ?, 1, 'c.md', ?, "
        "'document-hash', 'active', 'now')",
        (document_id, tx_id, f"{tx_id}/{document_id}"),
    )
    conn.execute(
        "INSERT INTO extraction_runs (id, transaction_id, document_id, provider, model, "
        "prompt_version, schema_version, extraction_json, status, created_at) "
        "VALUES (?, ?, ?, 'fake', 'fake-v1', 'v1', 'v1', ?, 'ok', 'now')",
        (run_id, tx_id, document_id, json.dumps(payload)),
    )
    version = create_initial_from_extraction(
        conn, transaction_id=tx_id, extraction_run_id=run_id, rules_payload=payload
    )
    validate_version(conn, version_id=version.id, confidence_threshold=0.7)

    spec = FundingScheduleSpec(
        overrides=(
            MilestoneReleaseOverride(
                rule_index=0,
                release_mode=RequestedReleaseMode.FIXED_TRANCHES,
                tranche_count=tranche_count,
            ),
        )
    )
    package = package_service.build_current_package(
        conn, transaction_id=tx_id, funding_schedule_spec=spec,
        capabilities=MOKA_STANDARD_PROFILE, actor_context=_actor("u-buyer", "entity-buyer"),
    )
    package = package_service.open_package(conn, package_id=package.id, actor_context=_actor("u-buyer", "entity-buyer"))
    conn.commit()
    _ratify_both(conn, package.id)
    assert conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()[0] == "active"
    return conn, tx_id, package.id


def _submit_verified_irsaliye(conn, tx_id, quantity, ref):
    evidence_service.submit_evidence(
        conn, transaction_id=tx_id, milestone_id=None, evidence_type="e_irsaliye",
        source="external_api", actor_context=_actor("u-seller", "entity-seller"),
        payload={"delivered_quantity": quantity}, verification_status="verified",
        external_reference=ref,
    )
    conn.commit()


def test_fixed_tranche_half_delivery_releases_two_of_four_units(tmp_path) -> None:
    conn, tx_id, _ = _seed_fixed_tranche_account(tmp_path, tranche_count=4)
    units = funding_units_repo.list_for_transaction(conn, tx_id)
    assert len(units) == 4  # 100 birim / 4 tranche

    _submit_verified_irsaliye(conn, tx_id, 50, "irsaliye-50")
    result = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path))

    # %50 teslim -> eşik 25/50 geçen U01+U02 release; U03/U04 (75/100) erken release YOK.
    assert len(result["approved_unit_ids"]) == 2
    assert result["settled"] is False
    statuses = {u["sequence"]: u["status"] for u in funding_units_repo.list_for_transaction(conn, tx_id)}
    assert statuses[1] == "approved" and statuses[2] == "approved"
    assert statuses[3] == "pool_created" and statuses[4] == "pool_created"

    # Replay: U01/U02 tekrar approve edilmez, U03/U04 hâlâ erken release edilmez.
    second = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path))
    assert second["approved_unit_ids"] == []
    assert conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE operation_type = 'approve_pool_payment'"
    ).fetchone()[0] == 2

    # Kalan teslim (delta) -> kümülatif 100 -> tüm tranche'lar release -> settled.
    _submit_verified_irsaliye(conn, tx_id, 50, "irsaliye-100")
    third = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path))
    assert len(third["approved_unit_ids"]) == 2
    assert third["settled"] is True
    assert conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()[0] == "settled"
    conn.close()


def test_all_or_nothing_releases_and_settles(tmp_path) -> None:
    conn, tx_id, _ = _seed_funded_account(tmp_path)
    # _PAYLOAD approval-only (required_evidence=contract -> effective boş) => eligible.
    result = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path))
    assert result is not None
    assert result["lifecycle_version"] == "account_v2"
    assert len(result["approved_unit_ids"]) == 1
    assert result["settled"] is True
    assert conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()[0] == "settled"
    statuses = [u["status"] for u in funding_units_repo.list_for_transaction(conn, tx_id)]
    assert statuses == ["approved"]
    conn.close()


def test_replay_does_not_reapprove_or_double_settle(tmp_path) -> None:
    conn, tx_id, _ = _seed_funded_account(tmp_path)
    first = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path))
    assert first["settled"] is True
    approve_ops_after_first = conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE operation_type = 'approve_pool_payment'"
    ).fetchone()[0]

    second = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path))
    # Zaten settled: account yolu tekrar release denemez.
    assert second is None or not second.get("approved_unit_ids")
    approve_ops_after_second = conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE operation_type = 'approve_pool_payment'"
    ).fetchone()[0]
    assert approve_ops_after_second == approve_ops_after_first
    conn.close()


def test_open_dispute_blocks_release(tmp_path) -> None:
    conn, tx_id, _ = _seed_funded_account(tmp_path)
    disputes_service.open_dispute(
        conn,
        transaction_id=tx_id,
        milestone_id=None,
        reason_code="QUALITY_ISSUE",
        description="Teslimat itirazı.",
        actor_context=_actor("u-seller", "entity-seller"),
    )
    conn.commit()

    result = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path))
    assert result is not None
    assert result["approved_unit_ids"] == []
    assert result["settled"] is False
    statuses = [u["status"] for u in funding_units_repo.list_for_transaction(conn, tx_id)]
    assert all(status == "pool_created" for status in statuses)
    assert conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()[0] == "active"
    conn.close()


def test_blocking_review_blocks_release_zero_provider_calls(tmp_path) -> None:
    conn, tx_id, _ = _seed_funded_account(tmp_path)
    review_service.open_case(
        conn,
        transaction_id=tx_id,
        phase="settlement",
        source_type="video",
        source_id=tx_id,
        reason_code="MANUAL_HOLD",
        title="Manuel hold",
        description="İnceleme gerekiyor.",
        severity="blocking",
        actor_context=ActorContext(actor_type="anonymous", auth_method="none"),
    )
    conn.commit()

    result = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path))
    assert result["approved_unit_ids"] == []
    assert conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE operation_type = 'approve_pool_payment'"
    ).fetchone()[0] == 0
    conn.close()


class _AlreadyApprovedGateway:
    """approve çağrısında PAYMENT_ALREADY_APPROVED döner ama detail approved gösterir."""

    def __init__(self) -> None:
        self._inner = FakePaymentGateway()
        self.approve_calls = 0

    def create_pool_payment(self, command):
        return self._inner.create_pool_payment(command)

    def approve_pool_payment(self, identifier):
        self.approve_calls += 1
        # Önce gerçekten approve et (state approved olsun), sonra already_approved sinyali ver.
        self._inner.approve_pool_payment(identifier)
        return ProviderOperationResult(
            outcome=ProviderOperationOutcome.FAILED,
            identifier=identifier,
            provider_code="PAYMENT_ALREADY_APPROVED",
            message="Zaten approve edildi.",
        )

    def undo_pool_approval(self, identifier):
        return self._inner.undo_pool_approval(identifier)

    def get_payment_detail(self, query):
        return self._inner.get_payment_detail(query)


def test_payment_already_approved_reconciles_as_success(tmp_path) -> None:
    conn, tx_id, _ = _seed_funded_account(tmp_path)
    # Pool'lar fake gateway ile oluşturuldu; aynı store'u paylaşan gateway ile
    # approve'u already-approved senaryosuna sok.
    from backend.app.repositories.provider_payments import SQLitePaymentStore

    gateway = _AlreadyApprovedGateway()
    gateway._inner = FakePaymentGateway(SQLitePaymentStore(conn))

    result = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path), gateway=gateway)
    assert result["settled"] is True
    assert len(result["approved_unit_ids"]) == 1
    statuses = [u["status"] for u in funding_units_repo.list_for_transaction(conn, tx_id)]
    assert statuses == ["approved"]
    conn.close()


# --- Blocker 2: approval_unknown reconcile (kör re-approve / kilitlenme yok) ---


class _UnknownFirstApproveGateway:
    """İlk approve UNKNOWN döner ve ödemeyi pool bırakır (timeout); sonraki
    çağrılar gerçekten approve eder. Reconcile detail(pool)->kontrollü retry."""

    def __init__(self, inner: FakePaymentGateway) -> None:
        self._inner = inner
        self._first_done = False
        self.approve_calls = 0

    def create_pool_payment(self, command):
        return self._inner.create_pool_payment(command)

    def approve_pool_payment(self, identifier):
        self.approve_calls += 1
        if not self._first_done:
            self._first_done = True
            return ProviderOperationResult(
                outcome=ProviderOperationOutcome.UNKNOWN,
                identifier=identifier,
                provider_code="TRANSPORT_TIMEOUT",
            )
        return self._inner.approve_pool_payment(identifier)

    def undo_pool_approval(self, identifier):
        return self._inner.undo_pool_approval(identifier)

    def get_payment_detail(self, query):
        return self._inner.get_payment_detail(query)


class _UnknownButApprovedGateway:
    """approve UNKNOWN döner ama ödemeyi gerçekten approve eder (detail approved)."""

    def __init__(self, inner: FakePaymentGateway) -> None:
        self._inner = inner
        self.approve_calls = 0

    def create_pool_payment(self, command):
        return self._inner.create_pool_payment(command)

    def approve_pool_payment(self, identifier):
        self.approve_calls += 1
        self._inner.approve_pool_payment(identifier)  # gerçekten approve
        return ProviderOperationResult(
            outcome=ProviderOperationOutcome.UNKNOWN,
            identifier=identifier,
            provider_code="TRANSPORT_TIMEOUT",
        )

    def undo_pool_approval(self, identifier):
        return self._inner.undo_pool_approval(identifier)

    def get_payment_detail(self, query):
        return self._inner.get_payment_detail(query)


def test_single_unit_approval_unknown_not_locked_and_recovers(tmp_path) -> None:
    conn, tx_id, _ = _seed_funded_account(tmp_path)
    gateway = _UnknownFirstApproveGateway(FakePaymentGateway(SQLitePaymentStore(conn)))

    first = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path), gateway=gateway)
    assert first is not None and first["settled"] is False
    assert [u["status"] for u in funding_units_repo.list_for_transaction(conn, tx_id)] == ["approval_unknown"]
    assert gateway.approve_calls == 1

    # Blocker: tek approval_unknown unit readiness'i None'a kilitlememeli.
    second = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path), gateway=gateway)
    assert second is not None
    assert second["settled"] is True
    assert [u["status"] for u in funding_units_repo.list_for_transaction(conn, tx_id)] == ["approved"]
    # İkinci approve yalnız detail(pool) reconcile'ından SONRA (kontrollü retry).
    assert gateway.approve_calls == 2
    conn.close()


def test_approval_unknown_detail_approved_reconciles_without_reapprove(tmp_path) -> None:
    conn, tx_id, _ = _seed_funded_account(tmp_path)
    gateway = _UnknownButApprovedGateway(FakePaymentGateway(SQLitePaymentStore(conn)))

    result = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path), gateway=gateway)
    # Unknown ama detail approved -> aynı değerlendirmede reconcile, kör re-approve YOK.
    assert result["settled"] is True
    assert gateway.approve_calls == 1
    assert [u["status"] for u in funding_units_repo.list_for_transaction(conn, tx_id)] == ["approved"]
    conn.close()


def test_multi_unit_approval_unknown_reconciles_on_retry(tmp_path) -> None:
    conn, tx_id, _ = _seed_fixed_tranche_account(tmp_path, tranche_count=4)
    _submit_verified_irsaliye(conn, tx_id, 100, "irsaliye-full")  # 4 unit eligible
    gateway = _UnknownFirstApproveGateway(FakePaymentGateway(SQLitePaymentStore(conn)))

    first = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path), gateway=gateway)
    statuses = sorted(u["status"] for u in funding_units_repo.list_for_transaction(conn, tx_id))
    # İlk unit unknown (pool), diğer üçü approved; milestone partially_released.
    assert statuses == ["approval_unknown", "approved", "approved", "approved"]
    assert first["settled"] is False

    second = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path), gateway=gateway)
    assert second["settled"] is True
    assert all(u["status"] == "approved" for u in funding_units_repo.list_for_transaction(conn, tx_id))
    conn.close()


# --- Blocker 1: gerçek video endpoint -> settlement -> blocking review ---


def test_video_endpoint_damage_opens_blocking_review_and_holds(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "6c.db"))
    conn, tx_id, _ = _seed_funded_account(tmp_path)
    # Video kanalını canlı policy'de aç (package snapshot locked kalır; readiness bozulmaz).
    conn.execute(
        "UPDATE tracking_policies SET tracking_mode = 'document_and_video' WHERE transaction_id = ?",
        (tx_id,),
    )
    session = create_real_session(conn, user_id="u-seller")
    conn.commit()
    conn.close()

    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    with TestClient(create_app()) as client:
        client.cookies.set("m4t_session", session.raw_token)
        resp = client.post(
            f"/api/transactions/{tx_id}/evidence/video",
            files={"file": ("teslimat_hasarli.mp4", b"fake-video-bytes", "video/mp4")},
            headers={
                "X-CSRF-Token": session.raw_csrf_token,
                "X-Acting-Entity-ID": "entity-seller",
            },
        )
        assert resp.status_code == 200, resp.text

    conn = make_db(tmp_path / "6c.db")
    try:
        # Yüksek güvenli hasar -> video review_required; settlement onu OKUR
        # (matched_box) ve blocking review açar; hiçbir unit approve edilmez.
        assert conn.execute(
            "SELECT COUNT(*) FROM review_cases WHERE transaction_id = ? "
            "AND source_type = 'video' AND status = 'open'",
            (tx_id,),
        ).fetchone()[0] == 1
        assert [
            u["status"] for u in funding_units_repo.list_for_transaction(conn, tx_id)
        ] == ["pool_created"]
        assert conn.execute(
            "SELECT state FROM transactions WHERE id = ?", (tx_id,)
        ).fetchone()[0] == "active"
    finally:
        conn.close()
