"""sqlite3 katmanı — ORM yok, stdlib yeterli (§5, Notes for Implementer).

`connect()` per-request/per-task bağlantı açar (WAL modu, foreign_keys açık);
`init_db()` tabloları `CREATE TABLE IF NOT EXISTS` ile kurar; `get_db()`
FastAPI dependency olarak kullanılır (başarıda commit, her durumda kapatma).
"""

from __future__ import annotations

import sqlite3
from typing import Iterator

from backend.app.config import Settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    state TEXT,
    buyer_token TEXT,
    seller_token TEXT,
    markdown TEXT,
    masked_markdown TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS extracted_rules (
    transaction_id TEXT,
    extraction_json TEXT,
    validator_status TEXT,
    validator_report TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    transaction_id TEXT,
    party TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT,
    event_type TEXT,
    payload TEXT,
    source TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS mock_payments (
    transaction_id TEXT,
    other_trx_code TEXT,
    virtual_pos_order_id TEXT,
    status TEXT,
    amount REAL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    transaction_id TEXT,
    bundle_json TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS tracking_policies (
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
);
"""


def connect(settings: Settings | None = None) -> sqlite3.Connection:
    """`settings.db_path`e sqlite3 bağlantısı açar; dizin yoksa oluşturur.

    `check_same_thread=False`: `BackgroundTasks` kendi bağlantısını bu
    fonksiyonla açar (aynı thread garantisi yok); her çağıran kendi
    bağlantısını sahiplenir, paylaşılmaz.
    """
    settings = settings or Settings.from_env()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Tabloları idempotent kurar; additive manager token migration'ını uygular."""
    conn.executescript(_SCHEMA)
    transaction_columns = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
    if "manager_token" not in transaction_columns:
        # Eski runtime transaction'larına token üretmez/backfill etmez; yalnızca
        # yeni işlemlerin kullanacağı nullable kolonu ekler.
        conn.execute("ALTER TABLE transactions ADD COLUMN manager_token TEXT")
    conn.commit()


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: bağlantı açar, `yield` eder, başarıda commit eder.

    İstisna durumunda commit atlanır (rollback sqlite3'ün varsayılan
    davranışıdır); bağlantı her durumda kapatılır.
    """
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
