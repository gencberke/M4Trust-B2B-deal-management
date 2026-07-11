"""Migration `005_participants_invitations` + `006_audit_events` doğrudan
`apply(conn)` ile test edilir (registry'ye henüz kayıtlı değiller — bkz.
modül docstring'leri: kayıt Berke'nin entegrasyon commit'idir)."""

from __future__ import annotations

import sqlite3

import pytest

from participants_fixtures import create_test_transaction, make_participants_db


@pytest.fixture()
def conn():
    connection = make_participants_db()
    try:
        yield connection
    finally:
        connection.close()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def test_005_and_006_create_expected_tables(conn) -> None:
    tables = _table_names(conn)
    assert {
        "transaction_participants",
        "transaction_assignments",
        "transaction_invitations",
        "audit_events",
    } <= tables


def test_transaction_participants_unique_transaction_role(conn) -> None:
    tx_id = create_test_transaction(conn)
    conn.execute(
        "INSERT INTO transaction_participants (id, transaction_id, role, status, created_at, updated_at) "
        "VALUES ('p1', ?, 'buyer', 'ready', datetime('now'), datetime('now'))",
        (tx_id,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO transaction_participants (id, transaction_id, role, status, created_at, updated_at) "
            "VALUES ('p2', ?, 'buyer', 'ready', datetime('now'), datetime('now'))",
            (tx_id,),
        )


def test_transaction_participants_allows_both_roles_for_same_transaction(conn) -> None:
    tx_id = create_test_transaction(conn)
    conn.execute(
        "INSERT INTO transaction_participants (id, transaction_id, role, status, created_at, updated_at) "
        "VALUES ('p1', ?, 'buyer', 'ready', datetime('now'), datetime('now'))",
        (tx_id,),
    )
    conn.execute(
        "INSERT INTO transaction_participants (id, transaction_id, role, status, created_at, updated_at) "
        "VALUES ('p2', ?, 'seller', 'invited', datetime('now'), datetime('now'))",
        (tx_id,),
    )
    rows = conn.execute(
        "SELECT role FROM transaction_participants WHERE transaction_id = ? ORDER BY role", (tx_id,)
    ).fetchall()
    assert [r["role"] for r in rows] == ["buyer", "seller"]


def test_transaction_participants_fk_rejects_unknown_transaction(conn) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO transaction_participants (id, transaction_id, role, status, created_at, updated_at) "
            "VALUES ('p1', 'does-not-exist', 'buyer', 'ready', datetime('now'), datetime('now'))"
        )


def test_transaction_invitations_token_hash_is_unique(conn) -> None:
    tx_id = create_test_transaction(conn)
    conn.execute(
        "INSERT INTO transaction_invitations (id, transaction_id, participant_role, "
        "invited_email_normalized, token_hash, expires_at, status, created_by_user_id, created_at) "
        "VALUES ('i1', ?, 'seller', 'a@example.com', 'hash-1', datetime('now'), 'pending', 'u1', datetime('now'))",
        (tx_id,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO transaction_invitations (id, transaction_id, participant_role, "
            "invited_email_normalized, token_hash, expires_at, status, created_by_user_id, created_at) "
            "VALUES ('i2', ?, 'seller', 'b@example.com', 'hash-1', datetime('now'), 'pending', 'u1', datetime('now'))",
            (tx_id,),
        )


def test_transaction_invitations_raw_token_column_does_not_exist(conn) -> None:
    """Raw token'ın hiçbir kolonda saklanmadığını şema seviyesinde doğrular."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(transaction_invitations)")}
    assert "raw_token" not in columns
    assert "token" not in columns
    assert "token_hash" in columns


def test_transaction_assignments_allows_nullable_participant_id(conn) -> None:
    tx_id = create_test_transaction(conn)
    conn.execute(
        "INSERT INTO transaction_assignments (id, transaction_id, participant_id, user_id, "
        "legal_entity_id, role, status, created_at) VALUES ('a1', ?, NULL, 'u1', 'e1', 'viewer', "
        "'active', datetime('now'))",
        (tx_id,),
    )
    row = conn.execute("SELECT * FROM transaction_assignments WHERE id = 'a1'").fetchone()
    assert row["participant_id"] is None


def test_transaction_assignments_fk_rejects_unknown_participant(conn) -> None:
    tx_id = create_test_transaction(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO transaction_assignments (id, transaction_id, participant_id, user_id, "
            "legal_entity_id, role, status, created_at) VALUES ('a1', ?, 'does-not-exist', 'u1', "
            "'e1', 'manager', 'active', datetime('now'))",
            (tx_id,),
        )


def test_audit_events_transaction_id_nullable(conn) -> None:
    conn.execute(
        "INSERT INTO audit_events (id, transaction_id, actor_type, action, target_type, "
        "target_id, metadata_json, created_at) VALUES ('ae1', NULL, 'system', 'x.y', 'entity', "
        "'e1', '{}', datetime('now'))"
    )
    row = conn.execute("SELECT * FROM audit_events WHERE id = 'ae1'").fetchone()
    assert row["transaction_id"] is None


def test_second_apply_of_005_and_006_is_not_silently_idempotent_by_design(conn) -> None:
    """Migration modülleri kendi idempotency'sini sağlamaz (runner sorumluluğu,
    schema_migrations tablosu üzerinden); ikinci `apply()` çağrısı `CREATE TABLE`
    çakışmasıyla patlamalı -- bu, runner'ın applied-marker olmadan iki kez
    çalıştırmaması gerektiğinin dolaylı kanıtıdır."""
    from importlib import import_module

    migration_005 = import_module("backend.app.db.migrations.005_participants_invitations")
    with pytest.raises(sqlite3.OperationalError):
        migration_005.apply(conn)
