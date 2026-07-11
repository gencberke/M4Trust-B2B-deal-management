"""Mock Moka sunucusu testleri (GATE M1-YUSUF, §22.4-§22.7 + §25 acceptance 1-9).

Kapsam: `plans/done/01_moka_contract_mock_and_client.md` Faz 1B "Yusuf —
feat/moka-mock-server". Bu testler mock'u doğrudan (`TestClient`) çağırır —
Berke'nin henüz yazılmamış gerçek HTTP client'ından bağımsızdır; client/mock
E2E zinciri ayrı bir gate'te (M1C-YUSUF) test edilir.

Her test kendi izole SQLite dosyasını kullanır (`MOCK_MOKA_DB_PATH` env
override, autouse fixture) — testler arası state sızıntısı olmaz.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.services.payments.moka.errors import (
    APPROVE_DEALER_PAYMENT_NOT_FOUND,
    APPROVE_IDENTIFIER_MUST_BE_GIVEN,
    APPROVE_PAYMENT_ALREADY_APPROVED,
    APPROVE_PAYMENT_IS_NOT_POOL_PAYMENT,
    AUTH_INVALID_ACCOUNT,
    AUTH_INVALID_REQUEST,
    AUTH_VIRTUAL_POS_NOT_FOUND,
    UNDO_DEALER_PAYMENT_NOT_FOUND,
    UNDO_IDENTIFIER_MUST_BE_GIVEN,
    UNDO_IDENTIFIERS_NOT_MATCH,
    UNDO_PAYMENT_IS_NOT_POOL_PAYMENT,
    UNDO_PAYMENT_NOT_APPROVED_YET,
)

_DEALER_CODE = "DEALER-DEMO-001"
_USERNAME = "m4trust_demo"
_PASSWORD = "demo-secret"
_INVALID_REQUEST_ENVELOPE = {
    "Data": None,
    "ResultCode": AUTH_INVALID_REQUEST,
    "ResultMessage": "",
    "Exception": None,
}
_PAYMENT_DEALER_ENDPOINTS = (
    "/PaymentDealer/DoDirectPayment",
    "/PaymentDealer/DoApprovePoolPayment",
    "/PaymentDealer/UndoApprovePoolPayment",
    "/PaymentDealer/GetDealerPaymentTrxDetailList",
    "/PaymentDealer/GetPaymentList",
)


def _check_key(dealer_code: str = _DEALER_CODE, username: str = _USERNAME, password: str = _PASSWORD) -> str:
    material = f"{dealer_code}MK{username}PD{password}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _auth_block(**overrides: str) -> dict:
    block = {
        "DealerCode": _DEALER_CODE,
        "Username": _USERNAME,
        "Password": _PASSWORD,
        "CheckKey": _check_key(),
    }
    block.update(overrides)
    return block


def _direct_payment_body(other_trx_code: str, *, card_token: str = "DEMO-TOKEN-SUCCESS", is_pool_payment: int = 1) -> dict:
    return {
        "PaymentDealerAuthentication": _auth_block(),
        "PaymentDealerRequest": {
            "CardHolderFullName": "Demo Alici",
            "CardToken": card_token,
            "Amount": "2500.00",
            "Currency": "TL",
            "InstallmentNumber": 1,
            "ClientIP": "127.0.0.1",
            "OtherTrxCode": other_trx_code,
            "IsPoolPayment": is_pool_payment,
            "IsTokenized": 0,
            "Software": "M4Trust-Backend/1.0",
            "Description": "test",
            "IsPreAuth": 0,
            "BuyerInformation": None,
        },
    }


@pytest.fixture(autouse=True)
def _isolated_mock_moka_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_MOKA_DB_PATH", str(tmp_path / "mock_moka_test.db"))
    monkeypatch.setenv("MOCK_MOKA_DEALER_CODE", _DEALER_CODE)
    monkeypatch.setenv("MOCK_MOKA_USERNAME", _USERNAME)
    monkeypatch.setenv("MOCK_MOKA_PASSWORD", _PASSWORD)
    monkeypatch.setenv("MOCK_MOKA_VIRTUAL_POS_ENABLED", "true")
    monkeypatch.setenv("MOCK_MOKA_FAULTS_ENABLED", "false")
    monkeypatch.setenv("MOCK_MOKA_TIMEOUT_AFTER_CREATE_DELAY_SECONDS", "0.01")


@pytest.fixture()
def client(tmp_path: Path):
    from backend.mock_moka.app import app as mock_moka_app

    with TestClient(mock_moka_app) as test_client:
        yield test_client


def _create_and_approve(client: TestClient, other_trx_code: str) -> str:
    create = client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body(other_trx_code))
    vpos_id = create.json()["Data"]["VirtualPosOrderId"]
    client.post(
        "/PaymentDealer/DoApprovePoolPayment",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": other_trx_code}},
    )
    return vpos_id


# --- DoDirectPayment (§22.4) ----------------------------------------------


def test_direct_payment_success_pool(client: TestClient) -> None:
    response = client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-001"))

    body = response.json()
    assert response.status_code == 200
    assert body["ResultCode"] == "Success"
    assert body["Data"]["IsSuccessful"] is True
    assert body["Data"]["VirtualPosOrderId"].startswith("ORDER-DEMO-")


def test_direct_payment_non_pool_creates_non_pool_payment(client: TestClient) -> None:
    client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-NONPOOL", is_pool_payment=0))

    approve = client.post(
        "/PaymentDealer/DoApprovePoolPayment",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": "TRX-NONPOOL"}},
    )

    assert approve.json()["ResultCode"] == APPROVE_PAYMENT_IS_NOT_POOL_PAYMENT


def test_direct_payment_invalid_account_wrong_password(client: TestClient) -> None:
    body = _direct_payment_body("TRX-002")
    body["PaymentDealerAuthentication"] = _auth_block(Password="wrong-password", CheckKey=_check_key(password="wrong-password"))

    response = client.post("/PaymentDealer/DoDirectPayment", json=body)

    assert response.json()["ResultCode"] == AUTH_INVALID_ACCOUNT


def test_direct_payment_invalid_request_empty_dealer_code(client: TestClient) -> None:
    body = _direct_payment_body("TRX-003")
    body["PaymentDealerAuthentication"] = _auth_block(DealerCode="")

    response = client.post("/PaymentDealer/DoDirectPayment", json=body)

    assert response.json()["ResultCode"] == AUTH_INVALID_REQUEST


def test_direct_payment_virtual_pos_disabled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_MOKA_VIRTUAL_POS_ENABLED", "false")

    response = client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-004"))

    assert response.json()["ResultCode"] == AUTH_VIRTUAL_POS_NOT_FOUND


def test_direct_payment_bank_decline(client: TestClient) -> None:
    response = client.post(
        "/PaymentDealer/DoDirectPayment",
        json=_direct_payment_body("TRX-005", card_token="DEMO-TOKEN-BANK-DECLINE"),
    )

    body = response.json()
    assert body["ResultCode"] == "Success"  # envelope katmanı başarılı (§2.2)
    assert body["Data"]["IsSuccessful"] is False
    assert body["Data"]["VirtualPosOrderId"] == ""


def test_direct_payment_duplicate_other_trx_code_is_idempotent(client: TestClient) -> None:
    first = client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-006"))
    second = client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-006"))

    assert first.json()["Data"]["VirtualPosOrderId"] == second.json()["Data"]["VirtualPosOrderId"]


def test_direct_payment_timeout_fault_persists_row_then_returns_after_delay(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_MOKA_FAULTS_ENABLED", "true")

    response = client.post(
        "/PaymentDealer/DoDirectPayment",
        json=_direct_payment_body("TRX-TIMEOUT", card_token="DEMO-TOKEN-TIMEOUT-AFTER-CREATE"),
    )
    assert response.status_code == 200
    assert response.json()["Data"]["IsSuccessful"] is True

    detail = client.post(
        "/PaymentDealer/GetDealerPaymentTrxDetailList",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": "TRX-TIMEOUT"}},
    )
    assert len(detail.json()["Data"]["TrxDetailList"]) == 1


def test_direct_payment_unknown_token_is_bank_decline_without_persistence(client: TestClient) -> None:
    response = client.post(
        "/PaymentDealer/DoDirectPayment",
        json=_direct_payment_body("TRX-UNKNOWN-TOKEN", card_token="ARBITRARY-UNKNOWN-TOKEN"),
    )

    assert response.status_code == 200
    assert response.json()["ResultCode"] == "Success"
    assert response.json()["Data"]["IsSuccessful"] is False
    assert response.json()["Data"]["ResultCode"] == "BankDeclined"

    detail = client.post(
        "/PaymentDealer/GetDealerPaymentTrxDetailList",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": "TRX-UNKNOWN-TOKEN"}},
    )
    assert detail.json()["Data"]["TrxDetailList"] == []


def test_direct_payment_timeout_fault_disabled_by_default(client: TestClient) -> None:
    # MOCK_MOKA_FAULTS_ENABLED=false (fixture default) -> demo token normal success gibi davranir.
    response = client.post(
        "/PaymentDealer/DoDirectPayment",
        json=_direct_payment_body("TRX-TIMEOUT-OFF", card_token="DEMO-TOKEN-TIMEOUT-AFTER-CREATE"),
    )

    assert response.status_code == 200
    assert response.json()["Data"]["IsSuccessful"] is True


# --- DoApprovePoolPayment (§22.5) -----------------------------------------


def test_approve_by_virtual_pos_order_id(client: TestClient) -> None:
    create = client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-010"))
    vpos_id = create.json()["Data"]["VirtualPosOrderId"]

    approve = client.post(
        "/PaymentDealer/DoApprovePoolPayment",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"VirtualPosOrderId": vpos_id}},
    )

    assert approve.json()["ResultCode"] == "Success"
    assert approve.json()["Data"]["IsSuccessful"] is True


def test_approve_by_other_trx_code(client: TestClient) -> None:
    client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-011"))

    approve = client.post(
        "/PaymentDealer/DoApprovePoolPayment",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": "TRX-011"}},
    )

    assert approve.json()["ResultCode"] == "Success"


def test_approve_without_any_identifier(client: TestClient) -> None:
    approve = client.post(
        "/PaymentDealer/DoApprovePoolPayment",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {}},
    )

    assert approve.json()["ResultCode"] == APPROVE_IDENTIFIER_MUST_BE_GIVEN


def test_approve_not_found(client: TestClient) -> None:
    approve = client.post(
        "/PaymentDealer/DoApprovePoolPayment",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": "TRX-NEVER"}},
    )

    assert approve.json()["ResultCode"] == APPROVE_DEALER_PAYMENT_NOT_FOUND


def test_approve_already_approved(client: TestClient) -> None:
    client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-012"))
    approve_body = {
        "PaymentDealerAuthentication": _auth_block(),
        "PaymentDealerRequest": {"OtherTrxCode": "TRX-012"},
    }
    client.post("/PaymentDealer/DoApprovePoolPayment", json=approve_body)

    second = client.post("/PaymentDealer/DoApprovePoolPayment", json=approve_body)

    assert second.json()["ResultCode"] == APPROVE_PAYMENT_ALREADY_APPROVED


# --- UndoApprovePoolPayment (§22.6) ---------------------------------------


def test_undo_after_approve_succeeds(client: TestClient) -> None:
    _create_and_approve(client, "TRX-020")

    undo = client.post(
        "/PaymentDealer/UndoApprovePoolPayment",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": "TRX-020"}},
    )

    assert undo.json()["ResultCode"] == "Success"
    assert undo.json()["Data"]["IsSuccessful"] is True


def test_undo_not_approved_yet(client: TestClient) -> None:
    client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-021"))

    undo = client.post(
        "/PaymentDealer/UndoApprovePoolPayment",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": "TRX-021"}},
    )

    assert undo.json()["ResultCode"] == UNDO_PAYMENT_NOT_APPROVED_YET


def test_undo_not_pool_payment(client: TestClient) -> None:
    client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-022", is_pool_payment=0))

    undo = client.post(
        "/PaymentDealer/UndoApprovePoolPayment",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": "TRX-022"}},
    )

    assert undo.json()["ResultCode"] == UNDO_PAYMENT_IS_NOT_POOL_PAYMENT


def test_undo_no_identifier(client: TestClient) -> None:
    undo = client.post(
        "/PaymentDealer/UndoApprovePoolPayment",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {}},
    )

    assert undo.json()["ResultCode"] == UNDO_IDENTIFIER_MUST_BE_GIVEN


def test_undo_not_found(client: TestClient) -> None:
    undo = client.post(
        "/PaymentDealer/UndoApprovePoolPayment",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": "TRX-NEVER"}},
    )

    assert undo.json()["ResultCode"] == UNDO_DEALER_PAYMENT_NOT_FOUND


def test_undo_mismatched_identifiers(client: TestClient) -> None:
    _create_and_approve(client, "TRX-023")
    client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-024"))

    undo = client.post(
        "/PaymentDealer/UndoApprovePoolPayment",
        json={
            "PaymentDealerAuthentication": _auth_block(),
            "PaymentDealerRequest": {
                "OtherTrxCode": "TRX-023",
                "VirtualPosOrderId": "ORDER-DEMO-does-not-belong-to-TRX-023",
            },
        },
    )

    # vpos bulunamıyor -> DealerPaymentNotFound (mismatch yalnız HER İKİSİ de bulunup
    # farklı ödemeye işaret ederse tetiklenir; burada vpos hiç yok).
    assert undo.json()["ResultCode"] == UNDO_DEALER_PAYMENT_NOT_FOUND


def test_undo_statement_closed_is_internal_failure_not_documented_code(client: TestClient) -> None:
    from backend.mock_moka.config import MockMokaSettings

    vpos_id = _create_and_approve(client, "TRX-025")
    settings = MockMokaSettings.from_env()
    conn = sqlite3.connect(str(settings.db_path))
    conn.execute("UPDATE dealer_payments SET statement_closed = 1 WHERE other_trx_code = ?", ("TRX-025",))
    conn.commit()
    conn.close()

    undo = client.post(
        "/PaymentDealer/UndoApprovePoolPayment",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"VirtualPosOrderId": vpos_id}},
    )

    assert undo.status_code == 409


# --- GetDealerPaymentTrxDetailList (§22.7) --------------------------------


def test_detail_query_pending_status(client: TestClient) -> None:
    client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-030"))

    detail = client.post(
        "/PaymentDealer/GetDealerPaymentTrxDetailList",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": "TRX-030"}},
    )

    entry = detail.json()["Data"]["TrxDetailList"][0]
    assert entry["PaymentStatus"] == 0
    assert entry["TrxStatus"] == 0


def test_detail_query_approved_status(client: TestClient) -> None:
    _create_and_approve(client, "TRX-031")

    detail = client.post(
        "/PaymentDealer/GetDealerPaymentTrxDetailList",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": "TRX-031"}},
    )

    entry = detail.json()["Data"]["TrxDetailList"][0]
    assert entry["PaymentStatus"] == 2
    assert entry["TrxStatus"] == 1


def test_detail_query_unknown_payment_returns_empty_list(client: TestClient) -> None:
    detail = client.post(
        "/PaymentDealer/GetDealerPaymentTrxDetailList",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {"OtherTrxCode": "TRX-NEVER"}},
    )

    assert detail.json()["ResultCode"] == "Success"
    assert detail.json()["Data"]["TrxDetailList"] == []


def test_detail_query_requires_an_identifier(client: TestClient) -> None:
    detail = client.post(
        "/PaymentDealer/GetDealerPaymentTrxDetailList",
        json={"PaymentDealerAuthentication": _auth_block(), "PaymentDealerRequest": {}},
    )

    assert detail.json()["ResultCode"] == AUTH_INVALID_REQUEST


# --- GetPaymentList (§14.1 best-effort) -----------------------------------


def test_get_payment_list_returns_all_created_payments(client: TestClient) -> None:
    client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-040"))
    client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-041"))

    listing = client.post("/PaymentDealer/GetPaymentList", json={"PaymentDealerAuthentication": _auth_block()})

    codes = {entry["OtherTrxCode"] for entry in listing.json()["Data"]["TrxDetailList"]}
    assert {"TRX-040", "TRX-041"} <= codes


# --- Secret leakage (§22.12, mock-side) -----------------------------------


@pytest.mark.parametrize("endpoint", _PAYMENT_DEALER_ENDPOINTS)
@pytest.mark.parametrize("payload", [{}, None])
def test_validation_failures_use_exact_invalid_request_envelope(
    client: TestClient, endpoint: str, payload: dict | None
) -> None:
    if payload is None:
        response = client.post(
            endpoint,
            content=b'{"broken":',
            headers={"Content-Type": "application/json"},
        )
    else:
        response = client.post(endpoint, json=payload)

    assert response.status_code == 200
    assert response.json() == _INVALID_REQUEST_ENVELOPE


@pytest.mark.parametrize(
    "body",
    [
        {"PaymentDealerAuthentication": _auth_block(CheckKey=None), "PaymentDealerRequest": {}},
        {"PaymentDealerAuthentication": {**_auth_block(), "Password": ["secret"]}, "PaymentDealerRequest": {}},
        {"PaymentDealerAuthentication": _auth_block()},
    ],
)
def test_missing_or_malformed_auth_and_request_never_leak_validation_details(
    client: TestClient, body: dict
) -> None:
    response = client.post("/PaymentDealer/DoDirectPayment", json=body)

    assert response.status_code == 200
    assert response.json() == _INVALID_REQUEST_ENVELOPE


def test_no_raw_secrets_persisted_in_mock_operations(client: TestClient) -> None:
    from backend.mock_moka.app import _record_operation
    from backend.mock_moka.config import MockMokaSettings

    client.post("/PaymentDealer/DoDirectPayment", json=_direct_payment_body("TRX-050"))

    settings = MockMokaSettings.from_env()
    conn = sqlite3.connect(str(settings.db_path))
    sensitive = {
        "Password": "raw-password",
        "CheckKey": "raw-check-key",
        "CardToken": "raw-card-token",
        "PAN": "4111111111111111",
        "CardNumber": "5555555555554444",
        "CVC": "123",
        "CVV": "456",
        "SecurityCode": "789",
        "CardHolderFullName": "Sensitive Person",
        "BuyerInformation": {"Email": "person@example.test", "Phone": "+905551112233"},
        "Address": "Sensitive Address 42",
        "ClientIP": "203.0.113.42",
    }
    _record_operation(
        conn,
        "RedactionProbe",
        "TRX-REDACTION",
        {"nested": sensitive},
        {"echo": sensitive, "message": "raw-card-token person@example.test 203.0.113.42"},
    )
    rows = conn.execute("SELECT redacted_request, redacted_response FROM mock_operations").fetchall()
    conn.close()

    assert rows
    for redacted_request, redacted_response in rows:
        combined = redacted_request + redacted_response
        persisted = [json.loads(redacted_request), json.loads(redacted_response)]

        def _string_leaves(value):
            if isinstance(value, dict):
                for child in value.values():
                    yield from _string_leaves(child)
            elif isinstance(value, list):
                for child in value:
                    yield from _string_leaves(child)
            elif isinstance(value, str):
                yield value

        leaves = set(_string_leaves(persisted))
        assert _PASSWORD not in combined
        assert _check_key() not in combined
        for raw_value in sensitive.values():
            if isinstance(raw_value, str):
                assert raw_value not in leaves
                if len(raw_value) > 3:
                    assert raw_value not in combined
        for raw_value in sensitive["BuyerInformation"].values():
            assert raw_value not in leaves
            assert raw_value not in combined
