"""Bugünkü runtime şemasının eksiksiz baseline migration'ı."""

from __future__ import annotations

import sqlite3

VERSION = "001"
NAME = "baseline_current_schema"

STATEMENTS = (
    """CREATE TABLE transactions (
        id TEXT PRIMARY KEY, state TEXT, buyer_token TEXT, seller_token TEXT,
        markdown TEXT, masked_markdown TEXT, created_at TEXT, manager_token TEXT
    )""",
    """CREATE TABLE extracted_rules (
        transaction_id TEXT, extraction_json TEXT, validator_status TEXT,
        validator_report TEXT, created_at TEXT
    )""",
    """CREATE TABLE approvals (
        transaction_id TEXT, party TEXT, created_at TEXT
    )""",
    """CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id TEXT, event_type TEXT,
        payload TEXT, source TEXT, created_at TEXT
    )""",
    """CREATE TABLE mock_payments (
        transaction_id TEXT, other_trx_code TEXT, virtual_pos_order_id TEXT,
        status TEXT, amount REAL, created_at TEXT
    )""",
    """CREATE TABLE evidence (
        transaction_id TEXT, bundle_json TEXT, created_at TEXT
    )""",
    """CREATE TABLE tracking_policies (
        transaction_id TEXT PRIMARY KEY,
        recommendation TEXT,
        recommendation_reason_codes TEXT NOT NULL DEFAULT '[]',
        manager_physical_delivery_confirmed INTEGER,
        tracking_mode TEXT NOT NULL DEFAULT 'off',
        video_role TEXT NOT NULL DEFAULT 'advisory',
        status TEXT NOT NULL DEFAULT 'draft',
        configured_at TEXT,
        locked_at TEXT,
        FOREIGN KEY (transaction_id) REFERENCES transactions(id)
    )""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
