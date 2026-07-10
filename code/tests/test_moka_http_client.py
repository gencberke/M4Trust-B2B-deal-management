"""M1-BERKE Moka HTTP client, serializer, mapper ve redaction testleri."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Callable

import httpx
import pytest

from backend.app.config import Settings
from backend.app.services.payments.domain import (
    CreatePoolPaymentCommand,
    PaymentDetailQuery,
    ProviderOperationOutcome,
    ProviderPaymentIdentifier,
    ProviderPaymentStatus,
)
from backend.app.services.payments.moka.authentication import generate_check_key
from backend.app.services.payments.moka.client import MokaPaymentDealerClient
from backend.app.services.payments.moka.errors import (
    AUTH_INVALID_ACCOUNT,
    ProviderContractViolation,
    ProviderValidationError,
)
from backend.app.services.payments.moka.redaction import redact_payload
from backend.app.services.payments.moka.serialization import (
    dumps_json,
    from_moka_currency,
    minor_units_to_decimal,
    to_moka_currency,
)
from backend.app.services.payments.ports import PaymentGateway

_PASSWORD = "demo-secret"
_CARD_TOKEN = "DEMO-TOKEN-SUCCESS"
_CHECK_KEY = "9e96d10765671b8c42b6736bd5aa061fee90ef15381e44350f038cd2e7a9673d"


@pytest.fixture()
def make_client():
    clients: list[httpx.Client] = []

    def _make(handler: Callable[[httpx.Request], httpx.Response]) -> MokaPaymentDealerClient:
        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(http_client)
        return MokaPaymentDealerClient(
            base_url="http://moka.test",
            dealer_code="DEALER-DEMO-001",
            username="m4trust_demo",
            password=_PASSWORD,
            card_token=_CARD_TOKEN,
            software="M4Trust-Backend/1.0",
            http_client=http_client,
        )

    yield _make
    for client in clients:
        client.close()


def _command() -> CreatePoolPaymentCommand:
    return CreatePoolPaymentCommand(
        amount_minor=250_000,
        currency="TRY",
        other_trx_code="M4T-TRX-0001",
        description="Milestone 1 - tranche 1",
    )


def _direct_success() -> dict:
    return {
        "Data": {
            "IsSuccessful": True,
            "ResultCode": "",
            "ResultMessage": "",
            "VirtualPosOrderId": "ORDER-DEMO-0001",
        },
        "ResultCode": "Success",
        "ResultMessage": "",
        "Exception": None,
    }


def test_check_key_matches_known_sha256_fixture_and_wrong_order_differs() -> None:
    actual = generate_check_key(
        dealer_code="DEALER-DEMO-001",
        username="m4trust_demo",
        password=_PASSWORD,
    )
    wrong_order = generate_check_key(
        dealer_code="m4trust_demo",
        username="DEALER-DEMO-001",
        password=_PASSWORD,
    )

    assert actual == _CHECK_KEY
    assert wrong_order != actual
    assert actual == actual.lower()


def test_currency_mapping_and_unsupported_currency_domain_error() -> None:
    assert to_moka_currency("TRY") == "TL"
    assert to_moka_currency("USD") == "USD"
    assert to_moka_currency("EUR") == "EUR"
    assert from_moka_currency("TL") == "TRY"

    with pytest.raises(ProviderValidationError) as exc_info:
        to_moka_currency("GBP")
    assert exc_info.value.result_code == "PROVIDER_UNSUPPORTED_CURRENCY"


def test_decimal_serialization_is_numeric_and_has_no_binary_float_drift() -> None:
    assert minor_units_to_decimal(250_000) == Decimal("2500.00")
    serialized = dumps_json({"Amount": Decimal("2500.00"), "Currency": "TL"})

    assert serialized == '{"Amount":2500.00,"Currency":"TL"}'
    assert '"2500.00"' not in serialized


def test_create_posts_exact_contract_and_maps_success_with_redacted_trace(make_client) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json=_direct_success())

    client = make_client(handler)
    assert isinstance(client, PaymentGateway)
    result = client.create_pool_payment(_command())

    assert result.outcome is ProviderOperationOutcome.SUCCESS
    assert result.payment is not None
    assert result.payment.amount_minor == 250_000
    assert result.payment.currency == "TRY"
    assert result.payment.status is ProviderPaymentStatus.POOL
    assert captured["path"] == "/PaymentDealer/DoDirectPayment"
    assert '"Amount":2500.00' in str(captured["body"])
    assert '"Currency":"TL"' in str(captured["body"])
    assert '"IsPoolPayment":1' in str(captured["body"])

    trace_text = json.dumps(client.last_trace, ensure_ascii=False)
    assert _PASSWORD not in trace_text
    assert _CARD_TOKEN not in trace_text
    assert _CHECK_KEY not in trace_text
    assert "M4Trust Demo" not in trace_text
    assert client.last_trace is not None
    authentication = client.last_trace["request"]["PaymentDealerAuthentication"]
    assert authentication["Password"] == "***"
    assert authentication["CheckKey"] == f"{_CHECK_KEY[:6]}...{_CHECK_KEY[-4:]}"


def test_envelope_failure_maps_to_failed_domain_result(make_client) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "Data": None,
                "ResultCode": AUTH_INVALID_ACCOUNT,
                "ResultMessage": "Bayi hesabı doğrulanamadı.",
                "Exception": None,
            },
        )

    result = make_client(handler).create_pool_payment(_command())

    assert result.outcome is ProviderOperationOutcome.FAILED
    assert result.provider_code == AUTH_INVALID_ACCOUNT
    assert result.payment is None


def test_bank_level_failure_is_distinct_from_envelope_failure(make_client) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "Data": {
                    "IsSuccessful": False,
                    "ResultCode": "BANK_DECLINED",
                    "ResultMessage": "İşlem banka tarafından reddedildi.",
                    "VirtualPosOrderId": "",
                },
                "ResultCode": "Success",
                "ResultMessage": "",
                "Exception": None,
            },
        )

    result = make_client(handler).create_pool_payment(_command())

    assert result.outcome is ProviderOperationOutcome.FAILED
    assert result.provider_code == "BANK_DECLINED"
    assert result.payment is None


def test_unknown_envelope_result_code_fails_closed(make_client) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "Data": None,
                "ResultCode": "PaymentDealer.Future.UnknownCode",
                "ResultMessage": "unknown",
                "Exception": None,
            },
        )

    with pytest.raises(ProviderContractViolation):
        make_client(handler).create_pool_payment(_command())


def test_approve_and_undo_use_exact_paths_without_partial_amount(make_client) -> None:
    captured: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append((request.url.path, request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "Data": {
                    "IsSuccessful": True,
                    "ResultCode": "",
                    "ResultMessage": "",
                    "VirtualPosOrderId": "ORDER-DEMO-0001",
                },
                "ResultCode": "Success",
                "ResultMessage": "",
                "Exception": None,
            },
        )

    client = make_client(handler)
    identifier = ProviderPaymentIdentifier(
        virtual_pos_order_id="ORDER-DEMO-0001",
        other_trx_code="M4T-TRX-0001",
    )

    assert client.approve_pool_payment(identifier).outcome is ProviderOperationOutcome.SUCCESS
    assert client.undo_pool_approval(identifier).outcome is ProviderOperationOutcome.SUCCESS
    assert [path for path, _body in captured] == [
        "/PaymentDealer/DoApprovePoolPayment",
        "/PaymentDealer/UndoApprovePoolPayment",
    ]
    for _path, body in captured:
        assert "capture_ratio" not in body
        assert "Amount" not in body


def test_redaction_defensively_masks_pan_cvc_and_buyer_contact() -> None:
    redacted = redact_payload(
        {
            "CardNumber": "4111111111111111",
            "CVC": "123",
            "BuyerInformation": "buyer@example.com +905551112233",
        }
    )
    rendered = json.dumps(redacted)

    assert "4111111111111111" not in rendered
    assert "123" not in rendered
    assert "buyer@example.com" not in rendered


@pytest.mark.parametrize("operation", ["create", "approve"])
def test_state_changing_timeout_returns_unknown_without_blind_retry(
    make_client,
    operation: str,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout after send", request=request)

    client = make_client(handler)
    if operation == "create":
        result = client.create_pool_payment(_command())
    else:
        result = client.approve_pool_payment(
            ProviderPaymentIdentifier(other_trx_code="M4T-TRX-0001")
        )

    assert result.outcome is ProviderOperationOutcome.UNKNOWN
    assert result.provider_code == "TRANSPORT_TIMEOUT"
    assert calls == 1


def test_detail_query_maps_moka_numeric_status_for_reconciliation(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/PaymentDealer/GetDealerPaymentTrxDetailList"
        return httpx.Response(
            200,
            json={
                "Data": {
                    "TrxDetailList": [
                        {
                            "OtherTrxCode": "M4T-TRX-0001",
                            "VirtualPosOrderId": "ORDER-DEMO-0001",
                            "PaymentStatus": 2,
                            "TrxStatus": 1,
                        }
                    ]
                },
                "ResultCode": "Success",
                "ResultMessage": "",
                "Exception": None,
            },
        )

    query = PaymentDetailQuery(
        identifier=ProviderPaymentIdentifier(other_trx_code="M4T-TRX-0001")
    )
    result = make_client(handler).get_payment_detail(query)

    assert result.outcome is ProviderOperationOutcome.SUCCESS
    assert result.payment is not None
    assert result.payment.status is ProviderPaymentStatus.APPROVED
    assert result.payment.amount_minor is None
    assert result.payment.currency is None


def test_settings_load_moka_fields_and_repr_masks_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_PROVIDER", "moka_http")
    monkeypatch.setenv("MOKA_BASE_URL", "http://moka.local:8001")
    monkeypatch.setenv("MOKA_DEALER_CODE", "DEALER-1")
    monkeypatch.setenv("MOKA_USERNAME", "demo-user")
    monkeypatch.setenv("MOKA_PASSWORD", _PASSWORD)
    monkeypatch.setenv("MOKA_CARD_TOKEN", _CARD_TOKEN)
    monkeypatch.setenv("MOKA_SOFTWARE", "M4Trust-Test")
    monkeypatch.setenv("MOKA_TIMEOUT_SECONDS", "17")
    monkeypatch.setenv("MOKA_CONTRACT_PROFILE", "moka_payment_dealer_pool_v1")

    settings = Settings.from_env()
    representation = repr(settings)

    assert settings.payment_provider == "moka_http"
    assert settings.moka_base_url == "http://moka.local:8001"
    assert settings.moka_timeout_seconds == 17.0
    assert _PASSWORD not in representation
    assert _CARD_TOKEN not in representation
    assert "moka_password='***'" in representation
    assert "moka_card_token='***'" in representation
