"""Migration `010_review_cases` doğrudan `apply(conn)` ile test edilir
(registry'ye henüz kayıtlı değil — Berke'nin Wave A entegrasyon commit'i ekler)."""

from __future__ import annotations

import sqlite3

import pytest

from participants_fixtures import create_test_transaction
from reviews_fixtures import make_reviews_db


@pytest.fixture()
def conn():
    connection = make_reviews_db()
    try:
        yield connection
    finally:
        connection.close()


def _insert_case(conn, tx_id, *, phase="pre_ratification", source_type="validator",
                  source_id="src-1", reason_code="VALIDATOR_NEEDS_REVIEW", severity="blocking",
                  status="open", case_id="c1"):
    conn.execute(
        "INSERT INTO review_cases (id, transaction_id, phase, source_type, source_id, "
        "reason_code, title, description, severity, status, opened_by_actor_type, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'title', 'desc', ?, ?, 'user', datetime('now'))",
        (case_id, tx_id, phase, source_type, source_id, reason_code, severity, status),
    )


def test_migration_creates_expected_tables(conn) -> None:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert {"review_cases", "review_actions"} <= tables


def test_review_case_fk_rejects_unknown_transaction(conn) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _insert_case(conn, "does-not-exist")


def test_duplicate_active_blocking_source_reason_rejected(conn) -> None:
    tx_id = create_test_transaction(conn)
    _insert_case(conn, tx_id, case_id="c1")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_case(conn, tx_id, case_id="c2")


def test_resolved_case_allows_new_case_for_same_source_reason(conn) -> None:
    tx_id = create_test_transaction(conn)
    _insert_case(conn, tx_id, case_id="c1", status="resolved")
    _insert_case(conn, tx_id, case_id="c2", status="open")  # should not raise
    rows = conn.execute(
        "SELECT id FROM review_cases WHERE transaction_id = ? ORDER BY id", (tx_id,)
    ).fetchall()
    assert [r["id"] for r in rows] == ["c1", "c2"]


def test_cancelled_case_allows_new_case_for_same_source_reason(conn) -> None:
    tx_id = create_test_transaction(conn)
    _insert_case(conn, tx_id, case_id="c1", status="cancelled")
    _insert_case(conn, tx_id, case_id="c2", status="open")


def test_warning_severity_has_no_dedup_constraint(conn) -> None:
    """Yalnız blocking case'ler için dedup uygulanır; iki warning case aynı
    source/reason ile birlikte açık kalabilir."""
    tx_id = create_test_transaction(conn)
    _insert_case(conn, tx_id, case_id="w1", severity="warning", status="open")
    _insert_case(conn, tx_id, case_id="w2", severity="warning", status="open")  # should not raise


def test_null_source_id_is_treated_as_empty_string_for_dedup(conn) -> None:
    tx_id = create_test_transaction(conn)
    conn.execute(
        "INSERT INTO review_cases (id, transaction_id, phase, source_type, source_id, "
        "reason_code, title, description, severity, status, opened_by_actor_type, created_at) "
        "VALUES ('c1', ?, 'pre_ratification', 'system', NULL, 'X', 't', 'd', 'blocking', 'open', "
        "'system', datetime('now'))",
        (tx_id,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO review_cases (id, transaction_id, phase, source_type, source_id, "
            "reason_code, title, description, severity, status, opened_by_actor_type, created_at) "
            "VALUES ('c2', ?, 'pre_ratification', 'system', NULL, 'X', 't', 'd', 'blocking', 'open', "
            "'system', datetime('now'))",
            (tx_id,),
        )


@pytest.mark.parametrize(
    "column,bad_value",
    [
        ("status", "not_a_real_status"),
        ("severity", "critical"),
        ("phase", "not_a_real_phase"),
        ("source_type", "not_a_real_source"),
    ],
)
def test_review_case_check_constraints_reject_invalid_enum_values(conn, column, bad_value) -> None:
    tx_id = create_test_transaction(conn)
    columns = {
        "phase": "pre_ratification",
        "source_type": "validator",
        "severity": "blocking",
        "status": "open",
    }
    columns[column] = bad_value
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO review_cases (id, transaction_id, phase, source_type, source_id, "
            "reason_code, title, description, severity, status, opened_by_actor_type, created_at) "
            "VALUES ('c1', ?, ?, ?, NULL, 'X', 't', 'd', ?, ?, 'system', datetime('now'))",
            (tx_id, columns["phase"], columns["source_type"], columns["severity"], columns["status"]),
        )


def test_review_action_check_constraint_rejects_invalid_action(conn) -> None:
    tx_id = create_test_transaction(conn)
    _insert_case(conn, tx_id)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO review_actions (id, review_case_id, actor_user_id, action, created_at) "
            "VALUES ('a1', 'c1', 'u1', 'not_a_real_action', datetime('now'))"
        )


def test_review_actions_append_only_rejects_update(conn) -> None:
    tx_id = create_test_transaction(conn)
    _insert_case(conn, tx_id)
    conn.execute(
        "INSERT INTO review_actions (id, review_case_id, actor_user_id, action, created_at) "
        "VALUES ('a1', 'c1', 'u1', 'comment', datetime('now'))"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE review_actions SET action = 'escalate' WHERE id = 'a1'")


def test_review_actions_append_only_rejects_delete(conn) -> None:
    tx_id = create_test_transaction(conn)
    _insert_case(conn, tx_id)
    conn.execute(
        "INSERT INTO review_actions (id, review_case_id, actor_user_id, action, created_at) "
        "VALUES ('a1', 'c1', 'u1', 'comment', datetime('now'))"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM review_actions WHERE id = 'a1'")


def test_review_action_fk_rejects_unknown_case(conn) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO review_actions (id, review_case_id, actor_user_id, action, created_at) "
            "VALUES ('a1', 'does-not-exist', 'u1', 'comment', datetime('now'))"
        )


def test_second_apply_is_not_idempotent_by_design(conn) -> None:
    """Migration modülünün kendisi idempotent değildir (runner sorumluluğu,
    schema_migrations üzerinden) -- ikinci apply CREATE TABLE çakışmasıyla patlamalı."""
    from importlib import import_module

    migration_010 = import_module("backend.app.db.migrations.010_review_cases")
    with pytest.raises(sqlite3.OperationalError):
        migration_010.apply(conn)
