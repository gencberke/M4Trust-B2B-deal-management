"""Transaction satırı, liste ve detay sorguları."""

from __future__ import annotations

from sqlite3 import Connection, Row


def load_transaction(conn: Connection, transaction_id: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()


def list_transaction_rows(conn: Connection) -> list[Row]:
    return conn.execute(
        "SELECT id, state, created_at FROM transactions ORDER BY created_at"
    ).fetchall()


def list_transaction_events(conn: Connection, transaction_id: str) -> list[Row]:
    return conn.execute(
        "SELECT id, event_type, payload, source, created_at FROM events "
        "WHERE transaction_id = ? ORDER BY id",
        (transaction_id,),
    ).fetchall()


def list_transaction_payments(conn: Connection, transaction_id: str) -> list[Row]:
    return conn.execute(
        "SELECT other_trx_code, virtual_pos_order_id, status, amount, created_at "
        "FROM mock_payments WHERE transaction_id = ?",
        (transaction_id,),
    ).fetchall()
