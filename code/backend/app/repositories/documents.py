"""`contract_documents` satır/sorgu erişimi (Plan 04 / Faz 4A).

Yalnız caller connection'ını kullanır; kendi commit/rollback/connect çağrısını
yapmaz. Immutable alanları (storage_ref/content_sha256/version) update eden
fonksiyon sunulmaz — yalnızca conversion sonrası doldurulan
`normalized_markdown_sha256` için tek amaçlı bir update vardır.
"""

from __future__ import annotations

from sqlite3 import Connection, Row


def insert_document(
    conn: Connection,
    *,
    document_id: str,
    transaction_id: str,
    version: int,
    original_filename: str,
    media_type: str | None,
    storage_ref: str,
    content_sha256: str,
    uploaded_by_user_id: str | None,
    now: str,
) -> None:
    conn.execute(
        """INSERT INTO contract_documents
        (id, transaction_id, version, original_filename, media_type, storage_ref,
         content_sha256, normalized_markdown_sha256, uploaded_by_user_id, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 'active', ?)""",
        (
            document_id,
            transaction_id,
            version,
            original_filename,
            media_type,
            storage_ref,
            content_sha256,
            uploaded_by_user_id,
            now,
        ),
    )


def get_by_id(conn: Connection, document_id: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM contract_documents WHERE id = ?", (document_id,)
    ).fetchone()


def set_normalized_markdown_sha256(
    conn: Connection, *, document_id: str, normalized_markdown_sha256: str
) -> None:
    conn.execute(
        "UPDATE contract_documents SET normalized_markdown_sha256 = ? WHERE id = ?",
        (normalized_markdown_sha256, document_id),
    )
