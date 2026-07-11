"""Ratification package SQL seam'i (Plan 04 / Faz 4D).

Bu repository yalnız caller connection'ını kullanır; commit/rollback/connect
yapmaz. Bound input alanlarını update eden fonksiyon sunmaz.
"""

from __future__ import annotations

from sqlite3 import Connection, Row


def insert_package(
    conn: Connection,
    *,
    package_id: str,
    transaction_id: str,
    version: int,
    document_id: str,
    rule_set_version_id: str,
    tracking_policy_version_id: str | None,
    canonical_payload_json: str,
    document_hash: str,
    rule_set_hash: str,
    participant_snapshot_hash: str,
    tracking_policy_hash: str,
    package_hash: str,
    status: str,
    created_at: str,
) -> None:
    conn.execute(
        """INSERT INTO ratification_packages (
            id, transaction_id, version, document_id, rule_set_version_id,
            tracking_policy_version_id, canonical_payload_json, document_hash,
            rule_set_hash, participant_snapshot_hash, tracking_policy_hash,
            package_hash, status, created_at, opened_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)""",
        (
            package_id,
            transaction_id,
            version,
            document_id,
            rule_set_version_id,
            tracking_policy_version_id,
            canonical_payload_json,
            document_hash,
            rule_set_hash,
            participant_snapshot_hash,
            tracking_policy_hash,
            package_hash,
            status,
            created_at,
        ),
    )


def get_by_id(conn: Connection, package_id: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM ratification_packages WHERE id = ?", (package_id,)
    ).fetchone()


def get_max_version(conn: Connection, transaction_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM ratification_packages WHERE transaction_id = ?",
        (transaction_id,),
    ).fetchone()
    return int(row[0])


def get_current(conn: Connection, transaction_id: str) -> Row | None:
    return conn.execute(
        """SELECT * FROM ratification_packages
        WHERE transaction_id = ? AND status NOT IN ('superseded', 'cancelled')
        ORDER BY version DESC LIMIT 1""",
        (transaction_id,),
    ).fetchone()


def mark_superseded(conn: Connection, package_id: str) -> None:
    conn.execute(
        "UPDATE ratification_packages SET status = 'superseded' WHERE id = ?",
        (package_id,),
    )


def update_opened(conn: Connection, *, package_id: str, opened_at: str) -> None:
    conn.execute(
        "UPDATE ratification_packages SET status = 'open', opened_at = ? "
        "WHERE id = ? AND status = 'draft'",
        (opened_at, package_id),
    )


def mark_complete(conn: Connection, *, package_id: str, completed_at: str) -> None:
    """4E'nin ratification wiring'i için dar status transition seam'i."""
    conn.execute(
        "UPDATE ratification_packages SET status = 'complete', completed_at = ? "
        "WHERE id = ? AND status = 'open'",
        (completed_at, package_id),
    )
