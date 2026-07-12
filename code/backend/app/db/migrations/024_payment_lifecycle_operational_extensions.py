"""Plan 07 payment lifecycle state ve bilateral resolution genişletmeleri.

016/017/023 merge edilmiş migration'lardır ve değiştirilmez. SQLite CHECK
constraint'leri additive olarak genişletilemediği için provider'a bağlı
tablolar, aynı kolon sözleşmesi korunarak bu migration'da güvenli biçimde
yeniden oluşturulur.
"""

from __future__ import annotations

import sqlite3

VERSION = "024"
NAME = "payment_lifecycle_operational_extensions"

_PROVIDER_PAYMENTS = """CREATE TABLE provider_payments (
    id TEXT PRIMARY KEY,
    funding_unit_id TEXT NOT NULL UNIQUE,
    provider_profile TEXT NOT NULL,
    other_trx_code TEXT NOT NULL,
    virtual_pos_order_id TEXT,
    dealer_payment_id TEXT,
    internal_status TEXT NOT NULL
        CHECK (internal_status IN (
            'pool_waiting', 'approved', 'approval_pending',
            'approval_unknown', 'approval_undone', 'refunded',
            'failed', 'unknown'
        )),
    moka_payment_status INTEGER,
    moka_trx_status INTEGER,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    currency TEXT NOT NULL,
    last_result_code TEXT,
    last_result_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider_profile, other_trx_code),
    UNIQUE(provider_profile, virtual_pos_order_id),
    FOREIGN KEY (funding_unit_id) REFERENCES funding_units(id)
)"""

_PROVIDER_OPERATIONS = """CREATE TABLE provider_operations (
    id TEXT PRIMARY KEY,
    provider_payment_id TEXT,
    funding_unit_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    redacted_request_json TEXT NOT NULL,
    response_json TEXT,
    http_status INTEGER,
    result_code TEXT,
    is_successful INTEGER,
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failed', 'unknown')),
    attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
    created_at TEXT NOT NULL,
    UNIQUE(idempotency_key, attempt_no),
    FOREIGN KEY (provider_payment_id) REFERENCES provider_payments(id),
    FOREIGN KEY (funding_unit_id) REFERENCES funding_units(id)
)"""

_RELEASE_INSTRUCTIONS = """CREATE TABLE release_instructions (
    id TEXT PRIMARY KEY,
    funding_unit_id TEXT NOT NULL,
    provider_payment_id TEXT NOT NULL,
    operation_type TEXT NOT NULL DEFAULT 'approve_pool_payment',
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    currency TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL
        CHECK (status IN ('created', 'submitted', 'confirmed', 'failed', 'unknown')),
    provider TEXT NOT NULL,
    provider_reference TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(funding_unit_id, operation_type),
    FOREIGN KEY (funding_unit_id) REFERENCES funding_units(id),
    FOREIGN KEY (provider_payment_id) REFERENCES provider_payments(id)
)"""

_FAKE_PROVIDER_PAYMENTS = """CREATE TABLE fake_provider_payments (
    id TEXT PRIMARY KEY,
    other_trx_code TEXT NOT NULL UNIQUE,
    virtual_pos_order_id TEXT NOT NULL UNIQUE,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    currency TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pool', 'approved', 'refunded')),
    is_pool_payment INTEGER NOT NULL DEFAULT 1 CHECK (is_pool_payment IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""


def _rebuild_provider_tables(conn: sqlite3.Connection) -> None:
    # Önce child tabloları adlandır; parent rename'i onların FK referanslarını
    # eski parent adına günceller. Yeni tablolar kurulduktan sonra eski kopyalar
    # güvenle silinir.
    conn.execute("ALTER TABLE provider_operations RENAME TO provider_operations_before_024")
    conn.execute("ALTER TABLE release_instructions RENAME TO release_instructions_before_024")
    conn.execute("ALTER TABLE provider_payments RENAME TO provider_payments_before_024")

    conn.execute(_PROVIDER_PAYMENTS)
    conn.execute(_PROVIDER_OPERATIONS)
    conn.execute(_RELEASE_INSTRUCTIONS)

    conn.execute(
        """INSERT INTO provider_payments (
            id, funding_unit_id, provider_profile, other_trx_code,
            virtual_pos_order_id, dealer_payment_id, internal_status,
            moka_payment_status, moka_trx_status, amount_minor, currency,
            last_result_code, last_result_message, created_at, updated_at
        ) SELECT id, funding_unit_id, provider_profile, other_trx_code,
            virtual_pos_order_id, dealer_payment_id, internal_status,
            moka_payment_status, moka_trx_status, amount_minor, currency,
            last_result_code, last_result_message, created_at, updated_at
        FROM provider_payments_before_024"""
    )
    conn.execute(
        """INSERT INTO provider_operations (
            id, provider_payment_id, funding_unit_id, operation_type, endpoint,
            idempotency_key, request_fingerprint, redacted_request_json,
            response_json, http_status, result_code, is_successful, outcome,
            attempt_no, created_at
        ) SELECT id, provider_payment_id, funding_unit_id, operation_type,
            endpoint, idempotency_key, request_fingerprint, redacted_request_json,
            response_json, http_status, result_code, is_successful, outcome,
            attempt_no, created_at
        FROM provider_operations_before_024"""
    )
    conn.execute(
        """INSERT INTO release_instructions (
            id, funding_unit_id, provider_payment_id, operation_type,
            amount_minor, currency, idempotency_key, status, provider,
            provider_reference, created_at, updated_at
        ) SELECT id, funding_unit_id, provider_payment_id, operation_type,
            amount_minor, currency, idempotency_key, status, provider,
            provider_reference, created_at, updated_at
        FROM release_instructions_before_024"""
    )

    conn.execute("DROP TABLE provider_operations_before_024")
    conn.execute("DROP TABLE release_instructions_before_024")
    conn.execute("DROP TABLE provider_payments_before_024")

    conn.execute(
        """CREATE INDEX idx_provider_operations_funding_unit
            ON provider_operations(funding_unit_id, operation_type, attempt_no)"""
    )
    conn.execute(
        """CREATE INDEX idx_release_instructions_status
            ON release_instructions(status, updated_at)"""
    )


def _rebuild_fake_provider_payments(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE fake_provider_payments RENAME TO fake_provider_payments_before_024")
    conn.execute(_FAKE_PROVIDER_PAYMENTS)
    conn.execute(
        """INSERT INTO fake_provider_payments (
            id, other_trx_code, virtual_pos_order_id, amount_minor, currency,
            status, is_pool_payment, created_at, updated_at
        ) SELECT id, other_trx_code, virtual_pos_order_id, amount_minor, currency,
            status, is_pool_payment, created_at, updated_at
        FROM fake_provider_payments_before_024"""
    )
    conn.execute("DROP TABLE fake_provider_payments_before_024")


def _create_resolution_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE payment_resolutions (
            id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL,
            funding_unit_id TEXT NOT NULL,
            review_case_id TEXT NOT NULL,
            operation_type TEXT NOT NULL
                CHECK (operation_type IN ('undo_approval', 'refund')),
            status TEXT NOT NULL DEFAULT 'requested'
                CHECK (status IN (
                    'requested', 'authorized', 'executing', 'executed',
                    'rejected', 'failed', 'unknown'
                )),
            idempotency_key TEXT NOT NULL UNIQUE,
            requested_by_user_id TEXT NOT NULL,
            requested_by_entity_id TEXT NOT NULL,
            executed_by_user_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (transaction_id) REFERENCES transactions(id),
            FOREIGN KEY (funding_unit_id) REFERENCES funding_units(id),
            FOREIGN KEY (review_case_id) REFERENCES review_cases(id)
        )"""
    )
    conn.execute(
        """CREATE INDEX idx_payment_resolutions_unit
            ON payment_resolutions(funding_unit_id, operation_type, status)"""
    )
    conn.execute(
        """CREATE INDEX idx_payment_resolutions_transaction
            ON payment_resolutions(transaction_id, created_at)"""
    )
    conn.execute(
        """CREATE TABLE payment_resolution_approvals (
            id TEXT PRIMARY KEY,
            resolution_id TEXT NOT NULL,
            participant_role TEXT NOT NULL CHECK (participant_role IN ('buyer', 'seller')),
            user_id TEXT NOT NULL,
            acting_entity_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(resolution_id, participant_role),
            FOREIGN KEY (resolution_id) REFERENCES payment_resolutions(id)
        )"""
    )
    conn.execute(
        """CREATE INDEX idx_payment_resolution_approvals_resolution
            ON payment_resolution_approvals(resolution_id, created_at)"""
    )
    conn.execute(
        """CREATE TRIGGER trg_payment_resolution_approvals_distinct_actors
            BEFORE INSERT ON payment_resolution_approvals
            WHEN EXISTS (
                SELECT 1 FROM payment_resolution_approvals existing
                WHERE existing.resolution_id = NEW.resolution_id
                  AND existing.participant_role != NEW.participant_role
                  AND (
                      existing.user_id = NEW.user_id
                      OR existing.acting_entity_id = NEW.acting_entity_id
                  )
            )
            BEGIN
                SELECT RAISE(ABORT,
                    'payment resolution buyer/seller actors must be distinct');
            END"""
    )


def apply(conn: sqlite3.Connection) -> None:
    _rebuild_provider_tables(conn)
    _rebuild_fake_provider_payments(conn)
    _create_resolution_tables(conn)
