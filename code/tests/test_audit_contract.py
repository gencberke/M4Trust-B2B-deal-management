"""`backend.app.services.audit` kontrat testleri (Plan 03 / Faz 3B — gerçek `audit_events`
implementasyonu; Plan 02'deki iskelet `NotImplementedError` fazı geride kaldı).

Kilitlenen kurallar: allowlist/redaksiyon INSERT'ten önce çalışır, `record()`
kendi connection'ını asla açmaz/commit etmez, business mutation rollback
olduğunda audit satırı da rollback olur, metadata stable JSON'dır, actor/
request_id/target doğru kolonlara yazılır.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from backend.app.services.audit import (
    AuditActor,
    DisallowedMetadataError,
    InvalidAuditTargetError,
    record,
)
from participants_fixtures import create_test_transaction, make_participants_db


@pytest.fixture()
def conn():
    connection = make_participants_db()
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture()
def actor() -> AuditActor:
    return AuditActor(
        actor_type="user", user_id="u1", acting_entity_id="e1", request_id="req-1"
    )


def _fetch_audit_row(conn: sqlite3.Connection, audit_id: str) -> sqlite3.Row:
    return conn.execute("SELECT * FROM audit_events WHERE id = ?", (audit_id,)).fetchone()


def test_record_writes_row_with_actor_entity_and_request_id(conn, actor) -> None:
    tx_id = create_test_transaction(conn)
    audit_id = record(
        conn, actor, "review.approve", f"transaction:{tx_id}", frozenset({"note"}),
        metadata={"note": "ok"}, transaction_id=tx_id,
    )
    row = _fetch_audit_row(conn, audit_id)
    assert row["actor_type"] == "user"
    assert row["actor_user_id"] == "u1"
    assert row["acting_entity_id"] == "e1"
    assert row["request_id"] == "req-1"
    assert row["action"] == "review.approve"
    assert row["target_type"] == "transaction"
    assert row["target_id"] == tx_id
    assert row["transaction_id"] == tx_id
    assert json.loads(row["metadata_json"]) == {"note": "ok"}


def test_record_never_opens_its_own_connection(monkeypatch: pytest.MonkeyPatch, conn, actor) -> None:
    def _forbidden_connect(*args, **kwargs):
        raise AssertionError("audit.record() kendi sqlite3.connect()'ini açmamalı.")

    monkeypatch.setattr(sqlite3, "connect", _forbidden_connect)

    tx_id = create_test_transaction(conn)
    record(conn, actor, "review.approve", f"transaction:{tx_id}", frozenset())


def test_record_does_not_commit_or_close_connection(conn, actor) -> None:
    tx_id = create_test_transaction(conn)
    record(conn, actor, "review.approve", f"transaction:{tx_id}", frozenset())
    # commit/close çağrılmadıysa connection hâlâ açık ve pending state okunabilir olmalı.
    row = conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()
    assert row["n"] == 1
    conn.rollback()
    row_after_rollback = conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()
    assert row_after_rollback["n"] == 0  # commit hiç çağrılmadığı için rollback ile satır kayboldu


def test_business_mutation_and_audit_share_same_transaction_rollback(conn, actor) -> None:
    """Business mutation (transactions.state) rollback olduğunda audit satırı da rollback olur."""
    tx_id = create_test_transaction(conn)
    conn.commit()  # baseline satır kalıcı olsun ki sonraki rollback yalnız mutation+audit'i geri alsın

    conn.execute("UPDATE transactions SET state = 'active' WHERE id = ?", (tx_id,))
    record(conn, actor, "transaction.activated", f"transaction:{tx_id}", frozenset(), transaction_id=tx_id)

    conn.rollback()

    state_row = conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    assert state_row["state"] == "awaiting_approval"
    count_row = conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()
    assert count_row["n"] == 0


def test_business_mutation_and_audit_commit_together(conn, actor) -> None:
    tx_id = create_test_transaction(conn)
    conn.execute("UPDATE transactions SET state = 'active' WHERE id = ?", (tx_id,))
    record(conn, actor, "transaction.activated", f"transaction:{tx_id}", frozenset(), transaction_id=tx_id)

    conn.commit()

    state_row = conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    assert state_row["state"] == "active"
    count_row = conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()
    assert count_row["n"] == 1


def test_record_rejects_metadata_outside_allowlist(conn, actor) -> None:
    tx_id = create_test_transaction(conn)
    with pytest.raises(DisallowedMetadataError):
        record(
            conn, actor, "review.approve", f"transaction:{tx_id}", frozenset({"note"}),
            metadata={"note": "ok", "extra_field": "not allowed"},
        )
    assert conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "forbidden_key",
    ["token", "buyer_token", "password", "checkkey", "card_token", "pan", "cvc", "cvv", "iban", "tckn"],
)
def test_record_rejects_forbidden_key_patterns_even_if_allowlisted(
    conn, actor, forbidden_key: str
) -> None:
    tx_id = create_test_transaction(conn)
    with pytest.raises(DisallowedMetadataError):
        record(
            conn, actor, "review.approve", f"transaction:{tx_id}", frozenset({forbidden_key}),
            metadata={forbidden_key: "irrelevant"},
        )
    assert conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()["n"] == 0


@pytest.mark.parametrize(
    "sensitive_value",
    [
        "TCKN 12345678901",
        "token=abc-super-secret",
        "abc-super-secret",
        "private@example.com",
        "TR330006100519786457841326",
        "4111111111111111",
        "Sensitive Person Home Address",
    ],
)
def test_record_rejects_sensitive_or_free_text_value_under_safe_key(
    conn, actor, sensitive_value: str
) -> None:
    tx_id = create_test_transaction(conn)
    with pytest.raises(DisallowedMetadataError):
        record(
            conn,
            actor,
            "review.approve",
            f"transaction:{tx_id}",
            frozenset({"note"}),
            metadata={"note": sensitive_value},
        )
    assert conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()["n"] == 0


def test_record_rejects_nested_metadata_even_if_allowlisted(conn, actor) -> None:
    tx_id = create_test_transaction(conn)
    with pytest.raises(DisallowedMetadataError):
        record(
            conn,
            actor,
            "review.approve",
            f"transaction:{tx_id}",
            frozenset({"note"}),
            metadata={"note": {"value": "token=abc"}},
        )


def test_metadata_validation_runs_before_any_insert(conn, actor) -> None:
    tx_id = create_test_transaction(conn)
    with pytest.raises(DisallowedMetadataError):
        record(conn, actor, "review.approve", f"transaction:{tx_id}", frozenset({"password"}), metadata={"password": "x"})
    assert conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()["n"] == 0


def test_record_rejects_target_without_colon(conn, actor) -> None:
    with pytest.raises(InvalidAuditTargetError):
        record(conn, actor, "review.approve", "malformed-target-no-colon", frozenset())


def test_record_rejects_target_with_empty_type_or_id(conn, actor) -> None:
    with pytest.raises(InvalidAuditTargetError):
        record(conn, actor, "review.approve", ":missing-type", frozenset())
    with pytest.raises(InvalidAuditTargetError):
        record(conn, actor, "review.approve", "missing-id:", frozenset())


def test_metadata_is_written_as_stable_sorted_json(conn, actor) -> None:
    tx_id = create_test_transaction(conn)
    audit_id = record(
        conn, actor, "review.approve", f"transaction:{tx_id}", frozenset({"b", "a"}),
        metadata={"b": 2, "a": 1},
    )
    row = _fetch_audit_row(conn, audit_id)
    assert row["metadata_json"] == '{"a": 1, "b": 2}'


def test_record_with_no_metadata_writes_empty_json_object(conn, actor) -> None:
    tx_id = create_test_transaction(conn)
    audit_id = record(conn, actor, "review.approve", f"transaction:{tx_id}", frozenset())
    row = _fetch_audit_row(conn, audit_id)
    assert row["metadata_json"] == "{}"


def test_record_allows_transaction_id_none_for_non_transaction_events(conn) -> None:
    actor = AuditActor(actor_type="system")
    audit_id = record(conn, actor, "entity.created", "legal_entity:abc123", frozenset())
    row = _fetch_audit_row(conn, audit_id)
    assert row["transaction_id"] is None
    assert row["actor_user_id"] is None
