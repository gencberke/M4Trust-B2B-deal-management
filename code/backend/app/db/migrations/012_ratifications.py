"""Account ratification persistence (Plan 04 / Wave B / Faz 4E, v2 §5.13).

Bir participant'ın belirli bir `ratification_packages` versiyonunu, kendi
kullanıcı + legal entity kimliğiyle onayladığının kanıtanabilir kaydı.
`UNIQUE(package_id, participant_id)` aynı participant'ın aynı package'ı iki
kez ratify etmesini DB seviyesinde engeller — `services/ratifications.py`'nin
idempotency'si bu constraint'e dayanır. Registry kaydı (`db/migrate.py`,
`db/migrations/__init__.py`) bilinçli olarak burada YAPILMAZ — Berke'nin
Wave B kapanış entegrasyon commit'i ekler. Branch testlerinde bu modül
doğrudan `apply(conn)` ile çağrılır.

`user_id`/`legal_entity_id` kolonlarına kasıtlı olarak FOREIGN KEY
eklenmedi (migration 005'teki `transaction_participants.legal_entity_id`
ile aynı gerekçe): `users`/`legal_entities` (003/004) bu migration'ın kendi
bağımlılık zincirinde değildir; `PRAGMA foreign_keys=ON` altında izole
branch testlerinde senkron olmayan satırlarla INSERT'i kırardı.
"""

from __future__ import annotations

import sqlite3

VERSION = "012"
NAME = "ratifications"

STATEMENTS = (
    """CREATE TABLE ratifications (
        id TEXT PRIMARY KEY,
        package_id TEXT NOT NULL,
        transaction_id TEXT NOT NULL,
        participant_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        legal_entity_id TEXT NOT NULL,
        participant_role TEXT NOT NULL CHECK (participant_role IN ('buyer', 'seller')),
        auth_method TEXT NOT NULL,
        approved_at TEXT NOT NULL,
        client_ip_hash TEXT,
        user_agent_summary TEXT,
        UNIQUE(package_id, participant_id),
        FOREIGN KEY (package_id) REFERENCES ratification_packages(id),
        FOREIGN KEY (transaction_id) REFERENCES transactions(id),
        FOREIGN KEY (participant_id) REFERENCES transaction_participants(id)
    )""",
    """CREATE INDEX idx_ratifications_package
        ON ratifications(package_id)""",
    """CREATE INDEX idx_ratifications_transaction
        ON ratifications(transaction_id)""",
    """CREATE INDEX idx_ratifications_participant
        ON ratifications(participant_id)""",
    """CREATE INDEX idx_ratifications_user
        ON ratifications(user_id)""",
    # Kanıt kaydı: kim tam olarak neyi onayladı sonradan değiştirilemez/silinemez.
    """CREATE TRIGGER trg_ratifications_no_update
        BEFORE UPDATE ON ratifications
        BEGIN
            SELECT RAISE(ABORT, 'ratifications is append-only: update yasak');
        END""",
    """CREATE TRIGGER trg_ratifications_no_delete
        BEFORE DELETE ON ratifications
        BEGIN
            SELECT RAISE(ABORT, 'ratifications is append-only: delete yasak');
        END""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
