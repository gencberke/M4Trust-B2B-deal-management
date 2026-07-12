"""Faz 6D — contract-faithful multi-release E2E + funding failure/reconciliation.

Berke'nin 6C'si (`test_settlement_funding_cutover.py`) account settlement yolunu
zaten `FakePaymentGateway` üzerinden kapsamlı biçimde test ediyor (all-or-nothing,
fixed-tranche, replay, açık dispute/review, PaymentAlreadyApproved reconciliation).
Bu dosya onu TEKRARLAMAZ; yalnız 6C'nin kapsamadığı iki kritik boşluğu doldurur:

1. Contract-faithful yol: gerçek `MokaPaymentDealerClient` gerçek `mock_moka` ASGI
   app'ine (ağsız, `TestClient` üzerinden -- ham `httpx.ASGITransport` sync client
   ile çalışmadığı için `test_moka_e2e_contract.py`'deki kurulan desen tekrar
   kullanılır) HTTP/JSON serileştirmesi dahil uçtan uca bağlanır.
2. Funding-CREATE aşamasında kısmi decline + reconciliation (6C'nin testleri
   yalnız approve-tarafı reconciliation'ı kapsıyordu).

`ensure_pool_funded`/`evaluate_settlement`'ın frozen `gateway=` enjeksiyon
seam'i kullanılır; `create_ratification`'ın kendi tetiklediği (gateway
parametresi olmayan) otomatik funding çağrısını gerçek/wrapper gateway'e
yönlendirmek için `funding_coordinator.make_payment_gateway` test kapsamında
monkeypatch edilir -- production kodu değişmez, yalnız test-seviyesi factory
override'ı (Berke'nin kendi `_AlreadyApprovedGateway` sarmalayıcı deseniyle
aynı yaklaşım).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.repositories import participants as participants_repo
from backend.app.schemas.payments import (
    FundingScheduleSpec,
    MilestoneReleaseOverride,
    RequestedReleaseMode,
)
from backend.app.services import participants as participants_service
from backend.app.services import ratification_package as package_service
from backend.app.services import settlement
from backend.app.services.access_control import ActorContext
from backend.app.services.payments import funding_coordinator
from backend.app.services.payments.domain import (
    MOKA_STANDARD_PROFILE,
    CreatePoolPaymentResult,
    ProviderOperationOutcome,
)
from backend.app.services.payments.moka.client import MokaPaymentDealerClient
from backend.app.services.payments.ports import FakePaymentGateway, InMemoryPaymentStore
from backend.app.services.rule_versions import create_initial_from_extraction, validate_version
from backend.app.services.tracking_policy import create_draft_policy
from backend.mock_moka import db as mock_db
from backend.mock_moka.app import app as mock_moka_app
from backend.mock_moka.config import MockMokaSettings
from reviews_fixtures import create_real_user
from test_ratifications import _PAYLOAD, _actor
from test_settlement_funding_cutover import (
    _create_entity,
    _ratify_both,
    _submit_verified_irsaliye,
    _seed_fixed_tranche_account,
    make_db,
)

_DEALER_CODE = "DEALER-6D-001"
_USERNAME = "m4trust_6d"
_PASSWORD = "demo-secret-6d"
_CARD_TOKEN = "DEMO-TOKEN-SUCCESS"
_BASE_URL = "http://testserver"


def _settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "6d.db")


@pytest.fixture(autouse=True)
def _isolated_mock_moka_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_MOKA_DB_PATH", str(tmp_path / "mock_moka_6d.db"))
    monkeypatch.setenv("MOCK_MOKA_DEALER_CODE", _DEALER_CODE)
    monkeypatch.setenv("MOCK_MOKA_USERNAME", _USERNAME)
    monkeypatch.setenv("MOCK_MOKA_PASSWORD", _PASSWORD)
    monkeypatch.setenv("MOCK_MOKA_VIRTUAL_POS_ENABLED", "true")
    monkeypatch.setenv("MOCK_MOKA_FAULTS_ENABLED", "false")

    settings = MockMokaSettings.from_env()
    conn = mock_db.connect(settings.db_path)
    try:
        mock_db.init_db(conn)
    finally:
        conn.close()


@pytest.fixture()
def real_moka_gateway(monkeypatch: pytest.MonkeyPatch):
    """Gerçek `MokaPaymentDealerClient`'ı ağsız `mock_moka` app'ine bağlar ve
    `funding_coordinator.make_payment_gateway`'i bu gateway'i döndürecek şekilde
    monkeypatch eder (yalnız test scope'unda; production kodu değişmez)."""

    test_client = TestClient(mock_moka_app, base_url=_BASE_URL)
    test_client.__enter__()
    gateway = MokaPaymentDealerClient(
        base_url=_BASE_URL,
        dealer_code=_DEALER_CODE,
        username=_USERNAME,
        password=_PASSWORD,
        card_token=_CARD_TOKEN,
        http_client=test_client,
    )
    monkeypatch.setattr(
        funding_coordinator, "make_payment_gateway", lambda settings, conn=None: gateway
    )
    yield gateway
    test_client.__exit__(None, None, None)


def test_contract_e2e_four_units_half_delivery_then_full_delivery(
    tmp_path, real_moka_gateway
) -> None:
    """Gerçek mock Moka protokolü: ratify -> 4 unit gerçek pool payment -> %50
    teslim -> U01+U02 gerçek approve -> U03/U04 pending -> tam teslim -> settled."""

    conn, tx_id, _ = _seed_fixed_tranche_account(tmp_path, tx_id="tx-6d-contract", tranche_count=4)

    units = funding_units_repo.list_for_transaction(conn, tx_id)
    assert len(units) == 4
    assert all(unit["status"] == "pool_created" for unit in units)
    trx_codes = [unit["other_trx_code"] for unit in units]
    assert len(set(trx_codes)) == 4  # her unit farklı OtherTrxCode kullanır

    create_ops = conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE operation_type = 'create_pool_payment'"
    ).fetchone()[0]
    assert create_ops == 4  # 4 ayrı gerçek create_pool_payment HTTP round-trip'i

    # approve_pool_payment amount/capture_ratio taşımaz -- yalnız identifier alır.
    approve_params = list(inspect.signature(real_moka_gateway.approve_pool_payment).parameters)
    assert approve_params == ["identifier"]

    _submit_verified_irsaliye(conn, tx_id, 50, "6d-irsaliye-50")
    result = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path), gateway=real_moka_gateway)
    assert len(result["approved_unit_ids"]) == 2
    assert result["settled"] is False
    statuses = {u["sequence"]: u["status"] for u in funding_units_repo.list_for_transaction(conn, tx_id)}
    assert statuses[1] == "approved" and statuses[2] == "approved"
    assert statuses[3] == "pool_created" and statuses[4] == "pool_created"

    approve_ops_after_first = conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE operation_type = 'approve_pool_payment'"
    ).fetchone()[0]
    assert approve_ops_after_first == 2

    # Replay: aynı evaluation'ı tekrar çalıştırmak U01/U02'yi tekrar approve etmez.
    replay = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path), gateway=real_moka_gateway)
    assert replay["approved_unit_ids"] == []
    approve_ops_after_replay = conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE operation_type = 'approve_pool_payment'"
    ).fetchone()[0]
    assert approve_ops_after_replay == 2

    # Kalan teslim: U03+U04 gerçek approve, transaction settled.
    _submit_verified_irsaliye(conn, tx_id, 100, "6d-irsaliye-100")
    final = settlement.evaluate_settlement(conn, tx_id, _settings(tmp_path), gateway=real_moka_gateway)
    assert len(final["approved_unit_ids"]) == 2
    assert final["settled"] is True
    assert conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (tx_id,)
    ).fetchone()[0] == "settled"
    conn.close()


def _seed_fixed_tranche_unratified(tmp_path, tx_id: str, *, tranche_count: int = 4):
    """`_seed_fixed_tranche_account`'ın aynısı, YALNIZ `_ratify_both` çağrılmadan
    önceki adımda durur -- caller kendi gateway'iyle ratify/fund tetikler."""

    conn = make_db(tmp_path / f"{tx_id}.db")
    create_real_user(conn, email_normalized=f"{tx_id}-buyer@example.com", user_id="u-buyer")
    create_real_user(conn, email_normalized=f"{tx_id}-seller@example.com", user_id="u-seller")
    _create_entity(conn, "entity-buyer", "u-buyer")
    _create_entity(conn, "entity-seller", "u-seller")

    payload = json.loads(json.dumps(_PAYLOAD))
    payload["commercial_terms"]["goods"][0]["quantity"] = 100.0
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
    return conn, tx_id, package.id


class _FirstCallDeclineGateway:
    """Yalnız İLK create_pool_payment çağrısını (unit sequence'ten bağımsız,
    iterasyon sırasına göre) reddeder; geri kalanı paylaşılan store'lu gerçek
    `FakePaymentGateway`'e delege eder. Approve/undo/detail her zaman inner'a gider."""

    def __init__(self, inner: FakePaymentGateway) -> None:
        self._inner = inner
        self.create_calls: list[str] = []

    def create_pool_payment(self, command):
        self.create_calls.append(command.other_trx_code)
        if len(self.create_calls) == 1:
            return CreatePoolPaymentResult(
                outcome=ProviderOperationOutcome.FAILED,
                provider_code="BANK_DECLINE",
                message="Test: ilk unit reddedildi.",
            )
        return self._inner.create_pool_payment(command)

    def approve_pool_payment(self, identifier):
        return self._inner.approve_pool_payment(identifier)

    def undo_pool_approval(self, identifier):
        return self._inner.undo_pool_approval(identifier)

    def get_payment_detail(self, query):
        return self._inner.get_payment_detail(query)


def test_partial_funding_decline_holds_and_retry_uses_same_trx_code(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bir unit'in pool oluşturma isteği reddedilirse: transaction funding_pending,
    blocking PAYMENT_POOL_CREATION_FAILED review case açılır, diğer başarılı
    unit'lerin kaydı kaybolmaz, kör retry yapılmaz. Retry aynı OtherTrxCode'u
    kullanır ve yalnız başarısız unit'i tekrar dener (başarılıları tekrar
    çağırmaz)."""

    store = InMemoryPaymentStore()
    declining = _FirstCallDeclineGateway(FakePaymentGateway(store))
    monkeypatch.setattr(
        funding_coordinator, "make_payment_gateway", lambda settings, conn=None: declining
    )

    conn, tx_id, package_id = _seed_fixed_tranche_unratified(
        tmp_path, "tx-6d-decline", tranche_count=4
    )
    _ratify_both(conn, package_id)

    tx_state = conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (tx_id,)
    ).fetchone()[0]
    assert tx_state == "funding_pending"

    units = funding_units_repo.list_for_transaction(conn, tx_id)
    assert len(units) == 4
    statuses = {u["sequence"]: u["status"] for u in units}
    assert statuses[1] == "pool_creation_failed"
    # Diğer 3 unit'in kaydı kaybolmadı -- gerçekten pool_created'a ulaştı.
    assert statuses[2] == "pool_created"
    assert statuses[3] == "pool_created"
    assert statuses[4] == "pool_created"
    original_trx_code = next(u["other_trx_code"] for u in units if u["sequence"] == 1)

    blocking_reviews = conn.execute(
        "SELECT COUNT(*) FROM review_cases WHERE transaction_id = ? "
        "AND reason_code = 'PAYMENT_POOL_CREATION_FAILED' AND severity = 'blocking'",
        (tx_id,),
    ).fetchone()[0]
    assert blocking_reviews == 1

    # Kör retry yok: declining gateway 4 kez çağrıldı (hepsi bu ilk turda), ikinci
    # bir ensure_pool_funded çağrısı yapılmadıkça yeni create isteği atılmaz.
    assert len(declining.create_calls) == 4

    # Retry: artık decline etmeyen (aynı store'lu) gerçek fake gateway ile.
    retry_gateway = FakePaymentGateway(store)
    result = funding_coordinator.ensure_pool_funded(
        conn, tx_id, package_id,
        ActorContext(actor_type="anonymous", auth_method="none"),
        gateway=retry_gateway,
    )
    assert result.status == "active"
    retried = {
        u["sequence"]: u
        for u in funding_units_repo.list_for_transaction(conn, tx_id)
    }
    assert retried[1]["status"] == "pool_created"
    assert retried[1]["other_trx_code"] == original_trx_code  # aynı kod korunur
    # Zaten pool_created olan 2/3/4 tekrar çağrılmadı (yalnız unit 1 retry edildi).
    retry_create_ops = conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE operation_type = 'create_pool_payment'"
    ).fetchone()[0]
    assert retry_create_ops == 5  # ilk turda 4 (1 failed + 3 success) + retry'de 1
    conn.close()
