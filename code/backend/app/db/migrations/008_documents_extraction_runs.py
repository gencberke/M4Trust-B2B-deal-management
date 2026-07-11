"""`contract_documents` + `extraction_runs` (Plan 04 / Faz 4A, v2 §5.8-5.9).

Additive ve atomik: mevcut tablolara dokunmaz. `contract_documents.storage_ref`
`DocumentStorageProvider`'ın döndürdüğü kalıcı referanstır (bkz.
`services/document_storage.py`); ham dosya bu tabloya girmez, yalnızca
provenance metadata'sı. `normalized_markdown_sha256` pipeline conversion
tamamlandıktan sonra ayrı bir UPDATE ile set edilir (initial INSERT'te NULL).

`extraction_runs` immutable'dır: raw model çıktısı tek seferde INSERT edilir,
update/delete yolu yoktur. Bu, uygulama katmanının disiplinine bırakılmaz —
DB seviyesinde `BEFORE UPDATE`/`BEFORE DELETE` trigger'ları ile fail-closed
uygulanır (uygulama hatası bile immutability'yi bozamaz).
"""

from __future__ import annotations

import sqlite3

VERSION = "008"
NAME = "documents_extraction_runs"

STATEMENTS = (
    """CREATE TABLE contract_documents (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        original_filename TEXT NOT NULL,
        media_type TEXT,
        storage_ref TEXT NOT NULL,
        content_sha256 TEXT NOT NULL,
        normalized_markdown_sha256 TEXT,
        uploaded_by_user_id TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        UNIQUE(transaction_id, version),
        UNIQUE(storage_ref),
        FOREIGN KEY (transaction_id) REFERENCES transactions(id)
    )""",
    """CREATE INDEX idx_contract_documents_transaction
        ON contract_documents(transaction_id)""",
    """CREATE TABLE extraction_runs (
        id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        rag_provenance_json TEXT NOT NULL DEFAULT '[]',
        privacy_summary_json TEXT NOT NULL DEFAULT '{}',
        extraction_json TEXT,
        status TEXT NOT NULL,
        failure_reason TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (transaction_id) REFERENCES transactions(id),
        FOREIGN KEY (document_id) REFERENCES contract_documents(id)
    )""",
    """CREATE INDEX idx_extraction_runs_transaction
        ON extraction_runs(transaction_id)""",
    """CREATE INDEX idx_extraction_runs_document
        ON extraction_runs(document_id)""",
    """CREATE TRIGGER trg_extraction_runs_no_update
        BEFORE UPDATE ON extraction_runs
        BEGIN
            SELECT RAISE(ABORT, 'extraction_runs is immutable: UPDATE not allowed');
        END""",
    """CREATE TRIGGER trg_extraction_runs_no_delete
        BEFORE DELETE ON extraction_runs
        BEGIN
            SELECT RAISE(ABORT, 'extraction_runs is immutable: DELETE not allowed');
        END""",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
