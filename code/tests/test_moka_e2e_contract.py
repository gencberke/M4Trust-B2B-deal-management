"""M4Trust client <-> mock Moka server E2E contract testleri (GATE M1C-YUSUF, §22.8, §22.12).

Kapsam: `plans/ready/01_moka_contract_mock_and_client.md` Faz 1C
"feat/moka-e2e-contract-tests". Berke'nin gerçek `MokaPaymentDealerClient`'ı
(hiç değiştirilmez) `fastapi.testclient.TestClient` üzerinden benim
`mock_moka` ASGI app'ime bağlanır — ağ yok, ama HTTP/JSON serileştirme dahil
gerçek uçtan uca yol izlenir. `TestClient`, `httpx.Client`'ın alt sınıfıdır
(`MokaPaymentDealerClient` sync `httpx.Client` bekler; ham
`httpx.ASGITransport` yalnız async'tir ve sync client ile çalışmaz — bu yüzden
`TestClient` kullanılır). Bu, Berke'nin kendi `test_moka_http_client.py`'sinden
farklıdır: o dosya `httpx.MockTransport` ile elle yazılmış canned response'lara
karşı yalnız client'ı test eder; burada gerçek mock SUNUCU davranışına karşı
test edilir.

`TestClient` yalnız `with TestClient(app) as tc:` bloğu içinde FastAPI lifespan
event'lerini (dolayısıyla `startup` hook'undaki `init_db`) tetikler; fixture
ayrıca garanti olması için şemayı elle de kurar.

İki negatif senaryo (`identifier'sız approve`, `non-pool approve`) gerçek
client'ın domain-seviyesi guard'ları (`ProviderPaymentIdentifier` en az bir
identifier ister; `create_pool_payment` her zaman `IsPoolPayment=1` gönderir)
yüzünden client üzerinden hiç üretilemez — bu iki durum zaten
`test_mock_moka_server.py`'de mock'un kendisine karşı test edildi. Burada
non-pool approve, kurulumu ham HTTP isteğiyle yapıp approve'u gerçek client
ile deneyerek test edilir (client'ın PaymentIsNotPoolPayment mapping'ini
gerçekten egzersiz eder).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.services.payments.domain import (
    CreatePoolPaymentCommand,
    PaymentDetailQuery,
    ProviderOperationOutcome,
    ProviderPaymentIdentifier,
    ProviderPaymentStatus,
)
from backend.app.services.payments.moka.client import MokaPaymentDealerClient
from backend.app.services.payments.moka.errors import (
    APPROVE_PAYMENT_ALREADY_APPROVED,
    APPROVE_PAYMENT_IS_NOT_POOL_PAYMENT,
    AUTH_INVALID_ACCOUNT,
)
from backend.mock_moka import db as mock_db
from backend.mock_moka.app import app as mock_moka_app
from backend.mock_moka.config import MockMokaSettings

_DEALER_CODE = "DEALER-DEMO-001"
_USERNAME = "m4trust_demo"
_PASSWORD = "demo-secret"
_CARD_TOKEN = "DEMO-TOKEN-SUCCESS"
_BASE_URL = "http://testserver"


@pytest.fixture(autouse=True)
def _isolated_mock_moka_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_MOKA_DB_PATH", str(tmp_path / "mock_moka_e2e.db"))
    monkeypatch.setenv("MOCK_MOKA_DEALER_CODE", _DEALER_CODE)
    monkeypatch.setenv("MOCK_MOKA_USERNAME", _USERNAME)
    monkeypatch.setenv("MOCK_MOKA_PASSWORD", _PASSWORD)
    monkeypatch.setenv("MOCK_MOKA_VIRTUAL_POS_ENABLED", "true")
    monkeypatch.setenv("MOCK_MOKA_FAULTS_ENABLED", "false")

    # ASGITransport lifespan event'lerini tetiklemez; şemayı burada elle kuruyoruz.
    settings = MockMokaSettings.from_env()
    conn = mock_db.connect(settings.db_path)
    try:
        mock_db.init_db(conn)
    finally:
        conn.close()


@pytest.fixture()
def make_client():
    """`MokaPaymentDealerClient`'ı `TestClient` (lifespan-aware) üzerinden kurar.

    `MokaPaymentDealerClient.close()` yalnız kendi açtığı `httpx.Client`'ı
    kapatır (`_owns_http_client`); burada dışarıdan verilen `TestClient`'ı biz
    açtığımız için kapatma sorumluluğu da bu fixture'da — testlerin
    `try/finally: client.close()` yazmasına gerek kalmaz.
    """

    created: list[TestClient] = []

    def _make(*, card_token: str = _CARD_TOKEN, password: str = _PASSWORD) -> MokaPaymentDealerClient:
        test_client = TestClient(mock_moka_app, base_url=_BASE_URL)
        test_client.__enter__()  # lifespan startup (init_db) tetiklenir
        created.append(test_client)
        return MokaPaymentDealerClient(
            base_url=_BASE_URL,
            dealer_code=_DEALER_CODE,
            username=_USERNAME,
            password=password,
            card_token=card_token,
            http_client=test_client,
        )

    yield _make

    for test_client in created:
        test_client.__exit__(None, None, None)


def _create_non_pool_payment_via_raw_request(other_trx_code: str) -> None:
    """Client her zaman IsPoolPayment=1 gönderir; non-pool kurulumunu ham HTTP ile yapar."""

    import hashlib

    check_key = hashlib.sha256(f"{_DEALER_CODE}MK{_USERNAME}PD{_PASSWORD}".encode("utf-8")).hexdigest()
    with TestClient(mock_moka_app, base_url=_BASE_URL) as raw_client:
        raw_client.post(
            "/PaymentDealer/DoDirectPayment",
            json={
                "PaymentDealerAuthentication": {
                    "DealerCode": _DEALER_CODE,
                    "Username": _USERNAME,
                    "Password": _PASSWORD,
                    "CheckKey": check_key,
                },
                "PaymentDealerRequest": {
                    "CardHolderFullName": "Demo Alici",
                    "CardToken": _CARD_TOKEN,
                    "Amount": "1000.00",
                    "Currency": "TL",
                    "InstallmentNumber": 1,
                    "ClientIP": "127.0.0.1",
                    "OtherTrxCode": other_trx_code,
                    "IsPoolPayment": 0,
                    "IsTokenized": 0,
                    "Software": "M4Trust-Backend/1.0",
                    "Description": "non-pool setup",
                    "IsPreAuth": 0,
                    "BuyerInformation": None,
                },
            },
        )


# --- §22.8 create -> approve -> already-approved -> undo -> detail reconcile ---


def test_full_chain_create_approve_already_approved_undo_detail_reconcile(make_client) -> None:
    client = make_client()
    command = CreatePoolPaymentCommand(
        amount_minor=250_000, currency="TRY", other_trx_code="E2E-TRX-001"
    )

    create_result = client.create_pool_payment(command)
    assert create_result.outcome == ProviderOperationOutcome.SUCCESS
    identifier = create_result.payment.identifier
    assert identifier.virtual_pos_order_id is not None
    assert identifier.other_trx_code == "E2E-TRX-001"

    approve_result = client.approve_pool_payment(identifier)
    assert approve_result.outcome == ProviderOperationOutcome.SUCCESS

    second_approve = client.approve_pool_payment(identifier)
    assert second_approve.outcome == ProviderOperationOutcome.FAILED
    assert second_approve.provider_code == APPROVE_PAYMENT_ALREADY_APPROVED

    undo_result = client.undo_pool_approval(identifier)
    assert undo_result.outcome == ProviderOperationOutcome.SUCCESS

    detail_result = client.get_payment_detail(PaymentDetailQuery(identifier=identifier))
    assert detail_result.outcome == ProviderOperationOutcome.SUCCESS
    assert detail_result.payment.status == ProviderPaymentStatus.POOL


# --- Negatifler --------------------------------------------------------------


def test_wrong_password_maps_to_invalid_account(make_client) -> None:
    client = make_client(password="wrong-password")
    command = CreatePoolPaymentCommand(
        amount_minor=100_000, currency="TRY", other_trx_code="E2E-TRX-BADAUTH"
    )

    result = client.create_pool_payment(command)

    assert result.outcome == ProviderOperationOutcome.FAILED
    assert result.provider_code == AUTH_INVALID_ACCOUNT


def test_non_pool_payment_approve_maps_to_not_pool_payment(make_client) -> None:
    _create_non_pool_payment_via_raw_request("E2E-TRX-NONPOOL")
    client = make_client()

    result = client.approve_pool_payment(
        ProviderPaymentIdentifier(other_trx_code="E2E-TRX-NONPOOL")
    )

    assert result.outcome == ProviderOperationOutcome.FAILED
    assert result.provider_code == APPROVE_PAYMENT_IS_NOT_POOL_PAYMENT


def test_bank_decline_is_failed_not_transport_error(make_client) -> None:
    client = make_client(card_token="DEMO-TOKEN-BANK-DECLINE")
    command = CreatePoolPaymentCommand(
        amount_minor=500_000, currency="TRY", other_trx_code="E2E-TRX-DECLINE"
    )

    result = client.create_pool_payment(command)

    assert result.outcome == ProviderOperationOutcome.FAILED
    assert result.provider_code == "BankDeclined"
    assert result.payment is None


def test_unknown_payment_detail_query_is_failed_not_found(make_client) -> None:
    client = make_client()

    result = client.get_payment_detail(
        PaymentDetailQuery(identifier=ProviderPaymentIdentifier(other_trx_code="E2E-NEVER-EXISTED"))
    )

    assert result.outcome == ProviderOperationOutcome.FAILED
    assert result.provider_code == "PROVIDER_PAYMENT_NOT_FOUND"


# --- §22.12 Secret leakage (client trace, gerçek sunucuya karşı) --------------


def test_client_trace_has_no_raw_secrets_after_real_round_trip(make_client) -> None:
    client = make_client()
    command = CreatePoolPaymentCommand(
        amount_minor=250_000, currency="TRY", other_trx_code="E2E-TRX-TRACE"
    )
    client.create_pool_payment(command)

    trace = client.last_trace
    assert trace is not None
    trace_text = str(trace)

    assert _PASSWORD not in trace_text
    assert _CARD_TOKEN not in trace_text
    assert trace["request"]["PaymentDealerAuthentication"]["Password"] == "***"
    assert trace["request"]["PaymentDealerAuthentication"]["CheckKey"] != ""
    assert "..." in trace["request"]["PaymentDealerAuthentication"]["CheckKey"]
    assert trace["request"]["PaymentDealerRequest"]["CardToken"].startswith("token_****")


def test_client_trace_masks_buyer_and_cardholder_contact_fields(make_client) -> None:
    client = make_client()
    command = CreatePoolPaymentCommand(
        amount_minor=100_000, currency="TRY", other_trx_code="E2E-TRX-CONTACT"
    )
    client.create_pool_payment(command)

    trace = client.last_trace
    assert trace["request"]["PaymentDealerRequest"]["CardHolderFullName"] == "***"
