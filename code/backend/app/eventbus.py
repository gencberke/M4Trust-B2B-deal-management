"""Event bus — `events` tablosuna §4.3 zarfıyla yazan tek giriş noktası.

§4.3'te tanımlı dokuz event tipi (referans; üretimleri sonraki fazlarda):
- contract_extracted
- rules_validated
- buyer_approved
- seller_approved
- e_irsaliye_received
- delivery_video_analyzed
- payment_decision_created
- mock_payment_executed
- dispute_opened

`emit()` bağlantıyı **commit etmez** — transaction'ın sınırını (bir istek/task
içinde birden çok emit + başka yazma) çağıran (örn. `db.get_db()` dependency'si
veya background task) belirler. Standalone çağrıldığında da çalışır (satır
insert edilir) ama kalıcı olması için çağıranın ayrıca `conn.commit()` etmesi
gerekir.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


def emit(
    conn: sqlite3.Connection,
    transaction_id: str,
    event_type: str,
    payload: dict,
    source: str,
) -> None:
    """`events` tablosuna bir kayıt ekler (§4.3 zarfı). Commit çağıranın işidir."""
    conn.execute(
        "INSERT INTO events (transaction_id, event_type, payload, source, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            transaction_id,
            event_type,
            json.dumps(payload, ensure_ascii=False),
            source,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
