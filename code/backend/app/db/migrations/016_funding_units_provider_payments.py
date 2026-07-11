"""Plan 06A funding-unit/provider-payment persistence."""

from __future__ import annotations

import sqlite3

VERSION = "016"
NAME = "funding_units_provider_payments"

STATEMENTS = (
    """CREATE TABLE funding_units (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        ratification_package_id TEXT NOT NULL,
        milestone_id TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence > 0),
        title TEXT NOT NULL,
        amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
        currency TEXT NOT NULL,
        eligibility_type TEXT NOT NULL,
        eligibility_payload_json TEXT NOT NULL,
        provider_profile TEXT NOT NULL,
        other_trx_code TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'planned'
            CHECK (status IN (
                'planned', 'pool_creation_pending', 'pool_created',
                'pool_creation_unknown', 'pool_creation_failed', 'approval_pending',
                'approval_unknown', 'approved', 'approval_undo_pending',
                'approval_undone', 'cancelled', 'refunded'
            )),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(provider_profile, other_trx_code),
        UNIQUE(ratification_package_id, sequence),
        FOREIGN KEY (transaction_id) REFERENCES transactions(id),
        FOREIGN KEY (ratification_package_id) REFERENCES ratification_packages(id),
        FOREIGN KEY (milestone_id) REFERENCES milestones(id)
    )""",
    """CREATE INDEX idx_funding_units_transaction_status
        ON funding_units(transaction_id, status)""",
    """CREATE INDEX idx_funding_units_milestone_sequence
        ON funding_units(milestone_id, sequence)""",
    """CREATE TABLE provider_payments (
        id TEXT PRIMARY KEY,
        funding_unit_id TEXT NOT NULL UNIQUE,
        provider_profile TEXT NOT NULL,
        other_trx_code TEXT NOT NULL,
        virtual_pos_order_id TEXT,
        dealer_payment_id TEXT,
        internal_status TEXT NOT NULL
            CHECK (internal_status IN (
                'pool_waiting', 'approved', 'approval_pending',
                'approval_unknown', 'failed', 'unknown'
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
    )""",
    """CREATE TABLE provider_operations (
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
    )""",
    """CREATE INDEX idx_provider_operations_funding_unit
        ON provider_operations(funding_unit_id, operation_type, attempt_no)""",
    """CREATE TABLE fake_provider_payments (
        id TEXT PRIMARY KEY,
        other_trx_code TEXT NOT NULL UNIQUE,
        virtual_pos_order_id TEXT NOT NULL UNIQUE,
        amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
        currency TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pool', 'approved')),
        is_pool_payment INTEGER NOT NULL DEFAULT 1 CHECK (is_pool_payment IN (0, 1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
