"""Moka contract DTO + hata kataloğu testleri (GATE M0-YUSUF, §22.1).

Kapsam: `plans/ready/01_moka_contract_mock_and_client.md` Faz 1A. Golden JSON
fixture'ları (`tests/fixtures/moka/*.json`) Moka'nın yayımlanmış contract
şeklini temsil eder; bu testler alan adı/casing'in ve hata kodu kataloğunun
merge sonrası donduğunu (freeze) doğrular — mock server (M1) ve gerçek HTTP
client (M1, Berke) bu modelleri değiştirmeden import eder.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.services.payments.moka import (
    KNOWN_RESULT_CODES,
    RESULT_CODE_TO_DOMAIN_ERROR,
    DoApprovePoolPaymentRequest,
    DoApprovePoolPaymentResponse,
    DoDirectPaymentRequest,
    DoDirectPaymentResponse,
    GetDealerPaymentTrxDetailListRequest,
    GetDealerPaymentTrxDetailListResponse,
    IdentifierFields,
    ProviderAuthenticationError,
    ProviderContractViolation,
    ProviderOperationUnknown,
    ProviderPaymentAlreadyApproved,
    UndoApprovePoolPaymentRequest,
    UndoApprovePoolPaymentResponse,
    map_result_code,
)
from backend.app.services.payments.moka.errors import (
    APPROVE_PAYMENT_ALREADY_APPROVED,
    AUTH_INVALID_ACCOUNT,
    UNEXPECTED_EXCEPTION,
)

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "moka"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _key_paths(value: object, prefix: str = "") -> set[str]:
    """Bir JSON değerinin tüm alan-adı yollarını çıkarır (casing kilidi için)."""

    paths: set[str] = set()
    if isinstance(value, dict):
        for key, sub_value in value.items():
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            paths |= _key_paths(sub_value, path)
    elif isinstance(value, list):
        for item in value:
            paths |= _key_paths(item, prefix)
    return paths


# --- §22.1 Contract DTO tests — exact casing -----------------------------


@pytest.mark.parametrize(
    ("fixture_name", "model_cls"),
    [
        ("do_direct_payment_request.json", DoDirectPaymentRequest),
        ("do_direct_payment_response_success.json", DoDirectPaymentResponse),
        ("do_direct_payment_response_error_invalid_account.json", DoDirectPaymentResponse),
        ("do_approve_pool_payment_request.json", DoApprovePoolPaymentRequest),
        ("do_approve_pool_payment_response_success.json", DoApprovePoolPaymentResponse),
        (
            "do_approve_pool_payment_response_already_approved.json",
            DoApprovePoolPaymentResponse,
        ),
        ("undo_approve_pool_payment_request.json", UndoApprovePoolPaymentRequest),
        ("undo_approve_pool_payment_response_success.json", UndoApprovePoolPaymentResponse),
        (
            "get_dealer_payment_trx_detail_list_request.json",
            GetDealerPaymentTrxDetailListRequest,
        ),
        (
            "get_dealer_payment_trx_detail_list_response_pending.json",
            GetDealerPaymentTrxDetailListResponse,
        ),
        (
            "get_dealer_payment_trx_detail_list_response_approved.json",
            GetDealerPaymentTrxDetailListResponse,
        ),
        ("unexpected_exception_response.json", DoDirectPaymentResponse),
    ],
)
def test_fixture_round_trips_with_exact_casing(fixture_name: str, model_cls) -> None:
    raw = _load(fixture_name)

    model = model_cls.model_validate(raw)
    dumped = json.loads(model.model_dump_json())

    assert _key_paths(dumped) == _key_paths(raw), (
        f"{fixture_name}: alan adı/casing kilidi bozuldu (extra/missing field)."
    )


def test_do_direct_payment_request_amount_parses_as_decimal_without_drift() -> None:
    raw = _load("do_direct_payment_request.json")
    model = DoDirectPaymentRequest.model_validate(raw)

    assert model.PaymentDealerRequest.Amount == Decimal("2500.00")
    assert model.PaymentDealerRequest.IsPoolPayment == 1
    assert model.PaymentDealerRequest.Currency == "TL"


def test_extra_field_is_rejected() -> None:
    raw = _load("do_direct_payment_response_success.json")
    raw["Data"]["UndocumentedField"] = "should not be accepted"

    with pytest.raises(ValidationError):
        DoDirectPaymentResponse.model_validate(raw)


def test_missing_required_field_is_rejected() -> None:
    raw = _load("do_direct_payment_response_success.json")
    del raw["Data"]["VirtualPosOrderId"]

    with pytest.raises(ValidationError):
        DoDirectPaymentResponse.model_validate(raw)


@pytest.mark.parametrize("model_cls", [IdentifierFields])
def test_approve_undo_identifier_fields_require_at_least_one(model_cls) -> None:
    with pytest.raises(ValidationError):
        model_cls.model_validate({"VirtualPosOrderId": None, "OtherTrxCode": None})

    # Tek biri yeterli.
    model_cls.model_validate({"VirtualPosOrderId": "ORDER-1", "OtherTrxCode": None})
    model_cls.model_validate({"VirtualPosOrderId": None, "OtherTrxCode": "TRX-1"})


# --- §15 Error catalog / mapping tests ------------------------------------


def test_every_known_result_code_has_a_domain_mapping() -> None:
    assert set(RESULT_CODE_TO_DOMAIN_ERROR.keys()) == KNOWN_RESULT_CODES


def test_documented_error_codes_map_to_expected_domain_types() -> None:
    assert isinstance(map_result_code(AUTH_INVALID_ACCOUNT), ProviderAuthenticationError)
    assert isinstance(
        map_result_code(APPROVE_PAYMENT_ALREADY_APPROVED), ProviderPaymentAlreadyApproved
    )
    assert isinstance(map_result_code(UNEXPECTED_EXCEPTION), ProviderOperationUnknown)


def test_unknown_result_code_fails_closed_to_contract_violation() -> None:
    error = map_result_code("PaymentDealer.SomeFutureEndpoint.NeverDocumented")

    assert isinstance(error, ProviderContractViolation)
    assert error.result_code == "PaymentDealer.SomeFutureEndpoint.NeverDocumented"


def test_error_response_fixture_maps_through_full_chain() -> None:
    raw = _load("do_approve_pool_payment_response_already_approved.json")
    response = DoApprovePoolPaymentResponse.model_validate(raw)

    error = map_result_code(response.ResultCode, result_message=response.ResultMessage)

    assert isinstance(error, ProviderPaymentAlreadyApproved)
