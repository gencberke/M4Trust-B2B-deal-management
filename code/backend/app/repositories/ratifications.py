"""`ratifications` satır/sorgu erişimi (Plan 04 / Wave B / Faz 4E).

Yalnız caller connection'ını kullanır; commit/rollback/connect yapmaz.
Append-only tablo — update/delete sunan fonksiyon YOKTUR (DB trigger'ları da
bunu fail-closed reddeder).
"""

from __future__ import annotations

from sqlite3 import Connection, Row


def insert(
    conn: Connection,
    *,
    id: str,
    package_id: str,
    transaction_id: str,
    participant_id: str,
    user_id: str,
    legal_entity_id: str,
    participant_role: str,
    auth_method: str,
    approved_at: str,
    client_ip_hash: str | None,
    user_agent_summary: str | None,
) -> None:
    conn.execute(
        """INSERT INTO ratifications (
            id, package_id, transaction_id, participant_id, user_id, legal_entity_id,
            participant_role, auth_method, approved_at, client_ip_hash, user_agent_summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            id,
            package_id,
            transaction_id,
            participant_id,
            user_id,
            legal_entity_id,
            participant_role,
            auth_method,
            approved_at,
            client_ip_hash,
            user_agent_summary,
        ),
    )


def get_by_package_and_participant(
    conn: Connection, *, package_id: str, participant_id: str
) -> Row | None:
    return conn.execute(
        "SELECT * FROM ratifications WHERE package_id = ? AND participant_id = ?",
        (package_id, participant_id),
    ).fetchone()


def get_by_package_and_user(conn: Connection, *, package_id: str, user_id: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM ratifications WHERE package_id = ? AND user_id = ?",
        (package_id, user_id),
    ).fetchone()


def list_by_package(conn: Connection, package_id: str) -> list[Row]:
    return conn.execute(
        "SELECT * FROM ratifications WHERE package_id = ? ORDER BY approved_at ASC",
        (package_id,),
    ).fetchall()


def distinct_roles_for_package(conn: Connection, package_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT participant_role FROM ratifications WHERE package_id = ?",
        (package_id,),
    ).fetchall()
    return {row["participant_role"] for row in rows}
