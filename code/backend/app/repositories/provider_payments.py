"""Provider payment/operation persistence and SQLite fake gateway store."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.services.payments.domain import (
    ProviderPaymentDetail,
    ProviderPaymentIdentifier,
    ProviderPaymentStatus,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_by_funding_unit(conn: sqlite3.Connection, funding_unit_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM provider_payments WHERE funding_unit_id = ?", (funding_unit_id,)
    ).fetchone()


def get_by_other_trx_code(
    conn: sqlite3.Connection, *, provider_profile: str, other_trx_code: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM provider_payments WHERE provider_profile = ? AND other_trx_code = ?",
        (provider_profile, other_trx_code),
    ).fetchone()


def upsert_payment(
    conn: sqlite3.Connection,
    *,
    payment_id: str,
    funding_unit_id: str,
    provider_profile: str,
    other_trx_code: str,
    virtual_pos_order_id: str | None,
    amount_minor: int,
    currency: str,
    internal_status: str,
    last_result_code: str | None = None,
    last_result_message: str | None = None,
    moka_payment_status: int | None = None,
    moka_trx_status: int | None = None,
) -> sqlite3.Row:
    existing = get_by_funding_unit(conn, funding_unit_id)
    if existing is None:
        now = _now()
        conn.execute(
            """INSERT INTO provider_payments (
                id, funding_unit_id, provider_profile, other_trx_code,
                virtual_pos_order_id, dealer_payment_id, internal_status,
                moka_payment_status, moka_trx_status, amount_minor, currency,
                last_result_code, last_result_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payment_id,
                funding_unit_id,
                provider_profile,
                other_trx_code,
                virtual_pos_order_id,
                internal_status,
                moka_payment_status,
                moka_trx_status,
                amount_minor,
                currency,
                last_result_code,
                last_result_message,
                now,
                now,
            ),
        )
    else:
        conn.execute(
            """UPDATE provider_payments SET
                virtual_pos_order_id = COALESCE(?, virtual_pos_order_id),
                internal_status = ?, moka_payment_status = ?, moka_trx_status = ?,
                last_result_code = ?, last_result_message = ?, updated_at = ?
            WHERE funding_unit_id = ?""",
            (
                virtual_pos_order_id,
                internal_status,
                moka_payment_status,
                moka_trx_status,
                last_result_code,
                last_result_message,
                _now(),
                funding_unit_id,
            ),
        )
    return get_by_funding_unit(conn, funding_unit_id)


def insert_operation(
    conn: sqlite3.Connection,
    *,
    funding_unit_id: str,
    provider_payment_id: str | None,
    operation_type: str,
    endpoint: str,
    idempotency_key: str,
    request_fingerprint: str,
    redacted_request_json: str,
    response_json: str | None,
    result_code: str | None,
    is_successful: bool | None,
    outcome: str,
    attempt_no: int,
    http_status: int | None = None,
) -> sqlite3.Row:
    operation_id = uuid4().hex
    conn.execute(
        """INSERT INTO provider_operations (
            id, provider_payment_id, funding_unit_id, operation_type, endpoint,
            idempotency_key, request_fingerprint, redacted_request_json,
            response_json, http_status, result_code, is_successful, outcome,
            attempt_no, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            operation_id,
            provider_payment_id,
            funding_unit_id,
            operation_type,
            endpoint,
            idempotency_key,
            request_fingerprint,
            redacted_request_json,
            response_json,
            http_status,
            result_code,
            None if is_successful is None else int(is_successful),
            outcome,
            attempt_no,
            _now(),
        ),
    )
    return conn.execute("SELECT * FROM provider_operations WHERE id = ?", (operation_id,)).fetchone()


def list_operations_for_transaction(
    conn: sqlite3.Connection, transaction_id: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT po.*, pp.provider_profile, pp.other_trx_code,
            pp.virtual_pos_order_id, pp.amount_minor, pp.currency,
            fu.transaction_id
        FROM provider_operations po
        JOIN funding_units fu ON fu.id = po.funding_unit_id
        LEFT JOIN provider_payments pp ON pp.id = po.provider_payment_id
        WHERE fu.transaction_id = ?
        ORDER BY po.created_at ASC, po.attempt_no ASC, po.id ASC""",
        (transaction_id,),
    ).fetchall()


class SQLitePaymentStore:
    """`FakePaymentGateway` için request'ler arası SQLite-backed store."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, identifier: ProviderPaymentIdentifier) -> ProviderPaymentDetail | None:
        if identifier.virtual_pos_order_id and identifier.other_trx_code:
            where = "virtual_pos_order_id = ? AND other_trx_code = ?"
            params = [identifier.virtual_pos_order_id, identifier.other_trx_code]
        elif identifier.virtual_pos_order_id:
            where = "virtual_pos_order_id = ?"
            params = [identifier.virtual_pos_order_id]
        elif identifier.other_trx_code:
            where = "other_trx_code = ?"
            params = [identifier.other_trx_code]
        else:
            return None
        row = self._conn.execute(
            "SELECT * FROM fake_provider_payments WHERE " + where, params
        ).fetchone()
        if row is None:
            return None
        return ProviderPaymentDetail(
            identifier=ProviderPaymentIdentifier(
                virtual_pos_order_id=row["virtual_pos_order_id"],
                other_trx_code=row["other_trx_code"],
            ),
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            status=ProviderPaymentStatus(row["status"]),
            is_pool_payment=bool(row["is_pool_payment"]),
        )

    def save(self, payment: ProviderPaymentDetail) -> None:
        identifier = payment.identifier
        if not identifier.other_trx_code or not identifier.virtual_pos_order_id:
            raise ValueError("SQLite fake store için iki payment identifier da gereklidir.")
        now = _now()
        self._conn.execute(
            """INSERT INTO fake_provider_payments (
                id, other_trx_code, virtual_pos_order_id, amount_minor, currency,
                status, is_pool_payment, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(other_trx_code) DO UPDATE SET
                virtual_pos_order_id = excluded.virtual_pos_order_id,
                amount_minor = excluded.amount_minor,
                currency = excluded.currency,
                status = excluded.status,
                is_pool_payment = excluded.is_pool_payment,
                updated_at = excluded.updated_at""",
            (
                uuid4().hex,
                identifier.other_trx_code,
                identifier.virtual_pos_order_id,
                payment.amount_minor,
                payment.currency,
                payment.status.value,
                int(payment.is_pool_payment),
                now,
                now,
            ),
        )
