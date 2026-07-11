"""`extraction_runs` satır/sorgu erişimi (Plan 04 / Faz 4A).

Yalnız caller connection'ını kullanır. Tablo DB seviyesinde immutable'dır
(bkz. migration 008 trigger'ları); bu modül bilinçli olarak update/delete
fonksiyonu SUNMAZ — run tek seferde tamamlanmış kayıt olarak insert edilir.
"""

from __future__ import annotations

from sqlite3 import Connection, Row


def insert_extraction_run(
    conn: Connection,
    *,
    run_id: str,
    transaction_id: str,
    document_id: str,
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: str,
    rag_provenance_json: str,
    privacy_summary_json: str,
    extraction_json: str | None,
    status: str,
    failure_reason: str | None,
    now: str,
) -> None:
    conn.execute(
        """INSERT INTO extraction_runs
        (id, transaction_id, document_id, provider, model, prompt_version, schema_version,
         rag_provenance_json, privacy_summary_json, extraction_json, status, failure_reason,
         created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            transaction_id,
            document_id,
            provider,
            model,
            prompt_version,
            schema_version,
            rag_provenance_json,
            privacy_summary_json,
            extraction_json,
            status,
            failure_reason,
            now,
        ),
    )


def get_by_id(conn: Connection, run_id: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM extraction_runs WHERE id = ?", (run_id,)
    ).fetchone()


def list_for_transaction(conn: Connection, transaction_id: str) -> list[Row]:
    return conn.execute(
        "SELECT * FROM extraction_runs WHERE transaction_id = ? ORDER BY created_at, rowid",
        (transaction_id,),
    ).fetchall()
