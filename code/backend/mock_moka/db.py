"""Mock Moka'nın kendi SQLite deposu.

Ana backend `backend/app/db.py`'den tamamen ayrıdır (kırmızı çizgi) — kendi
dosyasında (`mock_moka.db`, gitignore) ve kendi şemasında tutulur. `connect()`
her istekte taze bağlantı açar (ana app'in `db.py` deseniyle aynı — testlerde
`MOCK_MOKA_DB_PATH` env override'ının etkili olması için önemlidir); `init_db()`
tabloları bir kez, uygulama başlarken kurar. `mock_operations` yalnız
redaksiyonlu (Password/CheckKey/CardToken maskeli) istek/cevap saklar.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dealer_payments (
    other_trx_code TEXT PRIMARY KEY,
    virtual_pos_order_id TEXT UNIQUE NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    is_pool_payment INTEGER NOT NULL,
    payment_status INTEGER NOT NULL,
    trx_status INTEGER NOT NULL,
    statement_closed INTEGER NOT NULL DEFAULT 0,
    fault_profile TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mock_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL,
    other_trx_code TEXT,
    redacted_request TEXT NOT NULL,
    redacted_response TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    # `fault_profile` Plan 07'de eklendi; `CREATE TABLE IF NOT EXISTS` daha
    # eski bir dosyada tabloyu değiştirmez -- eksikse additive olarak ekle.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(dealer_payments)")}
    if "fault_profile" not in columns:
        conn.execute("ALTER TABLE dealer_payments ADD COLUMN fault_profile TEXT")
    conn.commit()


def mark_statement_closed(conn: sqlite3.Connection, other_trx_code: str) -> None:
    """Test-only helper: ilgili provider payment'i `statement_closed=true`
    durumuna getirir. Gerçek Moka'da bu, açık ekstre penceresi kapandığında
    bankanın kendisi tarafından belirlenir -- mock'ta hiçbir public HTTP
    endpoint'i bu alanı set etmez (dokümante edilmemiş davranış icat
    edilmez, §3.1); yalnız test fixture'ları doğrudan bu fonksiyonu çağırır."""
    conn.execute(
        "UPDATE dealer_payments SET statement_closed = 1 WHERE other_trx_code = ?",
        (other_trx_code,),
    )
    conn.commit()


def set_fault_profile(conn: sqlite3.Connection, other_trx_code: str, fault_profile: str | None) -> None:
    """Create sırasında persist edilen fault profile'ı (ör. `approve_timeout`)
    okuma/yazma seam'i -- yalnız bu modül içinden ve testlerden kullanılır."""
    conn.execute(
        "UPDATE dealer_payments SET fault_profile = ? WHERE other_trx_code = ?",
        (fault_profile, other_trx_code),
    )
    conn.commit()
