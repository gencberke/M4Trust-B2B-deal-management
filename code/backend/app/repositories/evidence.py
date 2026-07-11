"""`evidence_records` satır/sorgu erişimi (Plan 05 / Faz 5A).

Yalnız caller connection'ını kullanır; commit/rollback/connect yapmaz.
Bound alanları update eden fonksiyon sunulmaz (DB trigger'ı zaten reddeder,
bkz. migration 013) — yalnızca `mark_verified` ile `verification_status`/
`verified_at` değişebilir.
"""

from __future__ import annotations

from sqlite3 import Connection, Row


def insert(
    conn: Connection,
    *,
    id: str,
    transaction_id: str,
    milestone_id: str | None,
    evidence_type: str,
    source: str,
    submitted_by_user_id: str,
    submitted_by_entity_id: str,
    external_reference: str | None,
    storage_ref: str | None,
    file_sha256: str | None,
    payload_json: str,
    verification_status: str,
    analyzer_provider: str | None,
    analyzer_version: str | None,
    created_at: str,
) -> None:
    conn.execute(
        """INSERT INTO evidence_records (
            id, transaction_id, milestone_id, evidence_type, source,
            submitted_by_user_id, submitted_by_entity_id, external_reference,
            storage_ref, file_sha256, payload_json, verification_status,
            analyzer_provider, analyzer_version, created_at, verified_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
        (
            id,
            transaction_id,
            milestone_id,
            evidence_type,
            source,
            submitted_by_user_id,
            submitted_by_entity_id,
            external_reference,
            storage_ref,
            file_sha256,
            payload_json,
            verification_status,
            analyzer_provider,
            analyzer_version,
            created_at,
        ),
    )


def get_by_id(conn: Connection, evidence_id: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM evidence_records WHERE id = ?", (evidence_id,)
    ).fetchone()


def get_by_external_reference(
    conn: Connection, *, transaction_id: str, evidence_type: str, external_reference: str
) -> Row | None:
    return conn.execute(
        "SELECT * FROM evidence_records WHERE transaction_id = ? AND evidence_type = ? "
        "AND external_reference = ?",
        (transaction_id, evidence_type, external_reference),
    ).fetchone()


def get_by_file_sha256(conn: Connection, *, transaction_id: str, file_sha256: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM evidence_records WHERE transaction_id = ? AND file_sha256 = ?",
        (transaction_id, file_sha256),
    ).fetchone()


def list_for_transaction(conn: Connection, transaction_id: str) -> list[Row]:
    return conn.execute(
        "SELECT * FROM evidence_records WHERE transaction_id = ? ORDER BY created_at ASC",
        (transaction_id,),
    ).fetchall()


def list_for_milestone(conn: Connection, *, transaction_id: str, milestone_id: str) -> list[Row]:
    return conn.execute(
        "SELECT * FROM evidence_records WHERE transaction_id = ? AND milestone_id = ? "
        "ORDER BY created_at ASC",
        (transaction_id, milestone_id),
    ).fetchall()


def latest_for_type(
    conn: Connection, *, transaction_id: str, evidence_type: str, exclude_status: str = "rejected"
) -> Row | None:
    """Transaction-seviyesi (milestone_id IS NULL) en yeni, reddedilmemiş kaydı döner.

    Sıralama deterministiktir: `created_at` sonra `id` (stabil tie-break).
    """
    return conn.execute(
        "SELECT * FROM evidence_records WHERE transaction_id = ? AND evidence_type = ? "
        "AND milestone_id IS NULL AND verification_status != ? "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        (transaction_id, evidence_type, exclude_status),
    ).fetchone()


def mark_verified(conn: Connection, *, evidence_id: str, verification_status: str, verified_at: str) -> None:
    conn.execute(
        "UPDATE evidence_records SET verification_status = ?, verified_at = ? WHERE id = ?",
        (verification_status, verified_at, evidence_id),
    )
