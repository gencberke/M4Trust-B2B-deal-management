"""`services/payment_provider.py` testleri — MockMokaProvider + factory."""

from __future__ import annotations

import sqlite3

import pytest

from backend.app.config import Settings
from backend.app.db import init_db
from backend.app.services.payment_provider import MockMokaProvider, make_payment_provider


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)
    return connection


@pytest.fixture()
def provider(conn: sqlite3.Connection) -> MockMokaProvider:
    return MockMokaProvider(conn)


def _row_count(conn: sqlite3.Connection, other_trx_code: str) -> int:
    cursor = conn.execute(
        "SELECT COUNT(*) FROM mock_payments WHERE other_trx_code = ?",
        (other_trx_code,),
    )
    return cursor.fetchone()[0]


def test_create_pool_payment_inserts_row(provider: MockMokaProvider, conn: sqlite3.Connection) -> None:
    response = provider.create_pool_payment(amount=1000.0, currency="TRY", other_trx_code="TX-1")

    assert response["ResultCode"] == "Success"
    assert response["Data"]["IsSuccessful"] is True
    assert response["Data"]["VirtualPosOrderId"]
    assert _row_count(conn, "TX-1") == 1

    row = conn.execute(
        "SELECT status FROM mock_payments WHERE other_trx_code = ?", ("TX-1",)
    ).fetchone()
    assert row["status"] == "pool"


def test_create_pool_payment_idempotent(provider: MockMokaProvider, conn: sqlite3.Connection) -> None:
    first = provider.create_pool_payment(amount=500.0, currency="TRY", other_trx_code="TX-2")
    second = provider.create_pool_payment(amount=500.0, currency="TRY", other_trx_code="TX-2")

    assert first["Data"]["VirtualPosOrderId"] == second["Data"]["VirtualPosOrderId"]
    assert _row_count(conn, "TX-2") == 1


def test_approve_full_releases(provider: MockMokaProvider, conn: sqlite3.Connection) -> None:
    provider.create_pool_payment(amount=200.0, currency="TRY", other_trx_code="TX-3")

    response = provider.approve_pool_payment(other_trx_code="TX-3", capture_ratio=1.0)

    assert response["Data"]["IsSuccessful"] is True
    row = conn.execute(
        "SELECT status FROM mock_payments WHERE other_trx_code = ?", ("TX-3",)
    ).fetchone()
    assert row["status"] == "released"


def test_approve_partial_marks_partially_released(
    provider: MockMokaProvider, conn: sqlite3.Connection
) -> None:
    provider.create_pool_payment(amount=200.0, currency="TRY", other_trx_code="TX-4")

    response = provider.approve_pool_payment(other_trx_code="TX-4", capture_ratio=0.4)

    assert response["Data"]["IsSuccessful"] is True
    row = conn.execute(
        "SELECT status FROM mock_payments WHERE other_trx_code = ?", ("TX-4",)
    ).fetchone()
    assert row["status"] == "partially_released"


def test_approve_unknown_returns_failure(provider: MockMokaProvider) -> None:
    response = provider.approve_pool_payment(other_trx_code="UNKNOWN", capture_ratio=1.0)

    assert response["ResultCode"] == "Failed"
    assert response["Data"]["IsSuccessful"] is False


def test_get_payment_status_reflects_current_status(
    provider: MockMokaProvider, conn: sqlite3.Connection
) -> None:
    provider.create_pool_payment(amount=100.0, currency="TRY", other_trx_code="TX-5")
    provider.approve_pool_payment(other_trx_code="TX-5", capture_ratio=1.0)

    response = provider.get_payment_status(other_trx_code="TX-5")

    assert response["Data"]["status"] == "released"


def test_refund_sets_refunded_status(provider: MockMokaProvider, conn: sqlite3.Connection) -> None:
    provider.create_pool_payment(amount=100.0, currency="TRY", other_trx_code="TX-6")

    response = provider.refund_payment(other_trx_code="TX-6")

    assert response["Data"]["IsSuccessful"] is True
    row = conn.execute(
        "SELECT status FROM mock_payments WHERE other_trx_code = ?", ("TX-6",)
    ).fetchone()
    assert row["status"] == "refunded"


def test_undo_approve_returns_to_pool(provider: MockMokaProvider, conn: sqlite3.Connection) -> None:
    provider.create_pool_payment(amount=100.0, currency="TRY", other_trx_code="TX-7")
    provider.approve_pool_payment(other_trx_code="TX-7", capture_ratio=1.0)

    response = provider.undo_approve_pool_payment(other_trx_code="TX-7")

    assert response["Data"]["IsSuccessful"] is True
    row = conn.execute(
        "SELECT status FROM mock_payments WHERE other_trx_code = ?", ("TX-7",)
    ).fetchone()
    assert row["status"] == "pool"


def test_make_payment_provider_returns_mock(conn: sqlite3.Connection) -> None:
    settings = Settings(payment_provider="mock")

    provider = make_payment_provider(settings, conn)

    assert isinstance(provider, MockMokaProvider)


def test_make_payment_provider_raises_for_unknown(conn: sqlite3.Connection) -> None:
    settings = Settings(payment_provider="real")

    with pytest.raises(NotImplementedError):
        make_payment_provider(settings, conn)
