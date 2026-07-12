"""Faz 7B — mock Moka fault matrix testleri.

`DEMO-TOKEN-TIMEOUT-AFTER-CREATE` (persist + duplicate-create yok) zaten
`test_moka_e2e_contract.py::test_timeout_after_create_is_unknown_then_reconciles_without_duplicate`
ile kapsanıyor -- burada TEKRAR yazılmadı, yalnız matrise referans verilir.
Bu dosya yeni eklenen `DEMO-TOKEN-APPROVE-TIMEOUT` ve `statement_closed`
test-only fixture'ını, ve fault'ların yalnız `MOCK_MOKA_FAULTS_ENABLED=true`
iken aktif olduğunu kapsar.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import threading
import time
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
from backend.app.services.payments.moka.errors import APPROVE_PAYMENT_ALREADY_APPROVED
from backend.mock_moka import db as mock_db
from backend.mock_moka.app import app as mock_moka_app
from backend.mock_moka.config import MockMokaSettings

_DEALER_CODE = "DEALER-FAULT-001"
_USERNAME = "m4trust_fault"
_PASSWORD = "demo-secret-fault"
_APPROVE_TIMEOUT_TOKEN = "DEMO-TOKEN-APPROVE-TIMEOUT"
_SUCCESS_TOKEN = "DEMO-TOKEN-SUCCESS"
_BANK_DECLINE_TOKEN = "DEMO-TOKEN-BANK-DECLINE"
_BASE_URL = "http://testserver"


@pytest.fixture(autouse=True)
def _isolated_mock_moka_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_MOKA_DB_PATH", str(tmp_path / "mock_moka_faults.db"))
    monkeypatch.setenv("MOCK_MOKA_DEALER_CODE", _DEALER_CODE)
    monkeypatch.setenv("MOCK_MOKA_USERNAME", _USERNAME)
    monkeypatch.setenv("MOCK_MOKA_PASSWORD", _PASSWORD)
    monkeypatch.setenv("MOCK_MOKA_VIRTUAL_POS_ENABLED", "true")
    monkeypatch.setenv("MOCK_MOKA_FAULTS_ENABLED", "false")
    monkeypatch.setenv("MOCK_MOKA_TIMEOUT_AFTER_APPROVE_DELAY_SECONDS", "0.25")

    settings = MockMokaSettings.from_env()
    conn = mock_db.connect(settings.db_path)
    try:
        mock_db.init_db(conn)
    finally:
        conn.close()


@pytest.fixture()
def make_client():
    created: list[TestClient] = []

    def _make(*, card_token: str = _SUCCESS_TOKEN, timeout_seconds: float = 5.0) -> MokaPaymentDealerClient:
        test_client = TestClient(mock_moka_app, base_url=_BASE_URL)
        test_client.__enter__()
        created.append(test_client)
        return MokaPaymentDealerClient(
            base_url=_BASE_URL,
            dealer_code=_DEALER_CODE,
            username=_USERNAME,
            password=_PASSWORD,
            card_token=card_token,
            http_client=test_client,
        )

    yield _make
    for test_client in created:
        test_client.__exit__(None, None, None)


@pytest.fixture()
def live_mock_moka_url():
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(mock_moka_app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


def test_approve_timeout_is_unknown_then_detail_shows_approved(
    live_mock_moka_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_MOKA_FAULTS_ENABLED", "true")
    command = CreatePoolPaymentCommand(
        amount_minor=150_000, currency="TRY", other_trx_code="FAULT-APPROVE-TIMEOUT-1"
    )
    with MokaPaymentDealerClient(
        base_url=live_mock_moka_url, dealer_code=_DEALER_CODE, username=_USERNAME,
        password=_PASSWORD, card_token=_APPROVE_TIMEOUT_TOKEN, timeout_seconds=5,
    ) as setup_client:
        create_result = setup_client.create_pool_payment(command)
        assert create_result.outcome == ProviderOperationOutcome.SUCCESS
        identifier = create_result.payment.identifier

        with pytest.raises(Exception):
            # timeout_seconds client'ta ayrı bir kısa-timeout client ile approve
            # çağrılır; sunucu tarafı zaten approved yapıp gecikir -- client bunu
            # transport hatası olarak görmelidir.
            with MokaPaymentDealerClient(
                base_url=live_mock_moka_url, dealer_code=_DEALER_CODE, username=_USERNAME,
                password=_PASSWORD, card_token=_APPROVE_TIMEOUT_TOKEN, timeout_seconds=0.05,
            ) as timeout_client:
                result = timeout_client.approve_pool_payment(identifier)
                if result.outcome is not ProviderOperationOutcome.SUCCESS:
                    raise AssertionError("beklenen transport timeout gerçekleşmedi")

    time.sleep(0.35)
    settings = MockMokaSettings.from_env()
    conn = sqlite3.connect(str(settings.db_path))
    try:
        row = conn.execute(
            "SELECT payment_status FROM dealer_payments WHERE other_trx_code = ?",
            (command.other_trx_code,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == 2  # PAYMENT_STATUS_APPROVED -- provider state ÖNCE approved yapıldı

    monkeypatch.setenv("MOCK_MOKA_FAULTS_ENABLED", "false")
    with MokaPaymentDealerClient(
        base_url=live_mock_moka_url, dealer_code=_DEALER_CODE, username=_USERNAME,
        password=_PASSWORD, card_token=_SUCCESS_TOKEN, timeout_seconds=2,
    ) as reconcile_client:
        detail = reconcile_client.get_payment_detail(
            PaymentDetailQuery(identifier=ProviderPaymentIdentifier(other_trx_code=command.other_trx_code))
        )
    assert detail.outcome == ProviderOperationOutcome.SUCCESS
    assert detail.payment.status is ProviderPaymentStatus.APPROVED


def test_approve_timeout_fault_inactive_when_faults_disabled(make_client) -> None:
    # MOCK_MOKA_FAULTS_ENABLED=false (autouse fixture varsayılanı) -- approve
    # anında (gecikmesiz) normal biçimde sonuçlanmalı.
    client = make_client(card_token=_APPROVE_TIMEOUT_TOKEN)
    command = CreatePoolPaymentCommand(
        amount_minor=90_000, currency="TRY", other_trx_code="FAULT-APPROVE-TIMEOUT-DISABLED"
    )
    create_result = client.create_pool_payment(command)
    assert create_result.outcome == ProviderOperationOutcome.SUCCESS

    start = time.monotonic()
    approve_result = client.approve_pool_payment(create_result.payment.identifier)
    elapsed = time.monotonic() - start
    assert approve_result.outcome == ProviderOperationOutcome.SUCCESS
    assert elapsed < 0.2  # fault kapalıyken hiçbir gecikme yaşanmaz


def test_statement_closed_undo_does_not_change_state(make_client) -> None:
    client = make_client(card_token=_SUCCESS_TOKEN)
    command = CreatePoolPaymentCommand(
        amount_minor=75_000, currency="TRY", other_trx_code="FAULT-STATEMENT-CLOSED-1"
    )
    create_result = client.create_pool_payment(command)
    identifier = create_result.payment.identifier
    approve_result = client.approve_pool_payment(identifier)
    assert approve_result.outcome == ProviderOperationOutcome.SUCCESS

    settings = MockMokaSettings.from_env()
    conn = mock_db.connect(settings.db_path)
    try:
        mock_db.mark_statement_closed(conn, command.other_trx_code)
        before = conn.execute(
            "SELECT payment_status, trx_status, statement_closed FROM dealer_payments "
            "WHERE other_trx_code = ?",
            (command.other_trx_code,),
        ).fetchone()
    finally:
        conn.close()
    assert before["statement_closed"] == 1
    assert before["payment_status"] == 2  # hâlâ approved

    # `statement_closed` gerçek Moka public dokümanında exact code tanımlı
    # değil (§2.6) -- mock yeni bir ResultCode icat etmez, ham HTTP 409 döner;
    # client bunu documented bir ApiResponse zarfı olarak değil, transport
    # seviyesinde bir hata olarak görür (kontrollü failure, state değişmez).
    with pytest.raises(Exception):
        client.undo_pool_approval(identifier)

    conn = mock_db.connect(settings.db_path)
    try:
        after = conn.execute(
            "SELECT payment_status, trx_status FROM dealer_payments WHERE other_trx_code = ?",
            (command.other_trx_code,),
        ).fetchone()
    finally:
        conn.close()
    assert after["payment_status"] == before["payment_status"]
    assert after["trx_status"] == before["trx_status"]


def test_bank_decline_is_deterministic_across_repeated_calls(make_client) -> None:
    client = make_client(card_token=_BANK_DECLINE_TOKEN)
    results = [
        client.create_pool_payment(
            CreatePoolPaymentCommand(
                amount_minor=50_000, currency="TRY", other_trx_code=f"FAULT-DECLINE-{i}"
            )
        )
        for i in range(3)
    ]
    assert all(result.outcome == ProviderOperationOutcome.FAILED for result in results)
    assert len({result.provider_code for result in results}) == 1


def test_approve_already_approved_still_reports_expected_code(make_client) -> None:
    client = make_client(card_token=_SUCCESS_TOKEN)
    command = CreatePoolPaymentCommand(
        amount_minor=60_000, currency="TRY", other_trx_code="FAULT-ALREADY-APPROVED-1"
    )
    create_result = client.create_pool_payment(command)
    identifier = create_result.payment.identifier
    client.approve_pool_payment(identifier)
    second = client.approve_pool_payment(identifier)
    assert second.outcome == ProviderOperationOutcome.FAILED
    assert second.provider_code == APPROVE_PAYMENT_ALREADY_APPROVED


def test_no_raw_secrets_persisted_for_approve_timeout_fault(
    live_mock_moka_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_MOKA_FAULTS_ENABLED", "true")
    command = CreatePoolPaymentCommand(
        amount_minor=100_000, currency="TRY", other_trx_code="FAULT-SECRET-CHECK-1"
    )
    with MokaPaymentDealerClient(
        base_url=live_mock_moka_url, dealer_code=_DEALER_CODE, username=_USERNAME,
        password=_PASSWORD, card_token=_APPROVE_TIMEOUT_TOKEN, timeout_seconds=5,
    ) as setup_client:
        create_result = setup_client.create_pool_payment(command)
        identifier = create_result.payment.identifier
        try:
            with MokaPaymentDealerClient(
                base_url=live_mock_moka_url, dealer_code=_DEALER_CODE, username=_USERNAME,
                password=_PASSWORD, card_token=_APPROVE_TIMEOUT_TOKEN, timeout_seconds=0.05,
            ) as timeout_client:
                timeout_client.approve_pool_payment(identifier)
        except Exception:
            pass

    time.sleep(0.35)
    settings = MockMokaSettings.from_env()
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT redacted_request, redacted_response FROM mock_operations").fetchall()
    finally:
        conn.close()
    assert rows, "en az bir mock_operations kaydı bekleniyordu"
    blob = json.dumps([dict(row) for row in rows], ensure_ascii=False)
    for secret in (_PASSWORD, _APPROVE_TIMEOUT_TOKEN):
        assert secret not in blob
