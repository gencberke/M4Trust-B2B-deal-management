"""Plan 09 retention and backup/restore smoke tests."""

from __future__ import annotations

import base64
import hashlib
import sqlite3
from pathlib import Path

from backend.app.db import init_db
from backend.app.services.backup import create_backup, restore_backup, verify_backup
from backend.app.services.document_storage import LocalDocumentStorageProvider
from backend.app.services.retention import cleanup_transactions
from backend.app.services.storage_migration import migrate_storage

_KEY = base64.b64encode(b"r" * 32).decode("ascii")


def _storage(root: Path) -> LocalDocumentStorageProvider:
    return LocalDocumentStorageProvider(root=root, encryption_key=_KEY)


def _store(storage, tx: str, doc: str, content: bytes) -> str:
    return storage.store(
        transaction_id=tx,
        document_id=doc,
        original_filename="ignored.pdf",
        media_type="application/pdf",
        content=content,
        expected_sha256=hashlib.sha256(content).hexdigest(),
    ).storage_ref


def _seed(conn: sqlite3.Connection, storage) -> tuple[str, str]:
    conn.execute(
        "INSERT INTO transactions "
        "(id,state,buyer_token,seller_token,manager_token,markdown,masked_markdown,created_at) "
        "VALUES ('tx-terminal','settled','b','s','m','raw pii','masked','2026-01-01T00:00:00Z')"
    )
    raw_ref = _store(storage, "tx-terminal", "doc-raw", b"raw contract")
    markdown_ref = _store(storage, "tx-terminal", "markdown", b"converted markdown")
    conn.execute(
        "UPDATE transactions SET markdown_storage_ref=? WHERE id='tx-terminal'",
        (markdown_ref,),
    )
    conn.execute(
        """INSERT INTO contract_documents
        (id,transaction_id,version,original_filename,media_type,storage_ref,
         content_sha256,status,created_at)
        VALUES ('doc-raw','tx-terminal',1,'x.pdf','application/pdf',?,?, 'active',?)""",
        (raw_ref, hashlib.sha256(b"raw contract").hexdigest(), "2026-01-01T00:00:00Z"),
    )
    return raw_ref, markdown_ref


def test_retention_dry_run_execute_and_replay(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite"
    storage = _storage(tmp_path / "documents")
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        init_db(conn)
        raw_ref, markdown_ref = _seed(conn, storage)
        conn.commit()

        dry = cleanup_transactions(conn, storage, ["tx-terminal"], dry_run=True)
        assert dry.blobs_planned == 2
        assert storage.read_bytes(raw_ref) == b"raw contract"

        result = cleanup_transactions(conn, storage, ["tx-terminal"], dry_run=False)
        conn.commit()
        assert result.blobs_deleted == 2
        row = conn.execute(
            "SELECT markdown,masked_markdown,markdown_storage_ref,markdown_deleted_at "
            "FROM transactions WHERE id='tx-terminal'"
        ).fetchone()
        assert row["markdown"] is None and row["masked_markdown"] is None
        assert row["markdown_storage_ref"] is None and row["markdown_deleted_at"]
        assert conn.execute(
            "SELECT retention_deleted_at FROM contract_documents WHERE id='doc-raw'"
        ).fetchone()[0]

        replay = cleanup_transactions(conn, storage, ["tx-terminal"], dry_run=False)
        assert replay.blobs_planned == replay.blobs_deleted == 0


def test_retention_never_deletes_active_transaction(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite"
    storage = _storage(tmp_path / "documents")
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.execute(
            "INSERT INTO transactions (id,state,markdown,masked_markdown,created_at) "
            "VALUES ('tx-active','active','raw','masked','2026-01-01T00:00:00Z')"
        )
        result = cleanup_transactions(conn, storage, ["tx-active"], dry_run=False)
        assert result.skipped_active == 1
        assert conn.execute(
            "SELECT markdown FROM transactions WHERE id='tx-active'"
        ).fetchone()[0] == "raw"


def test_backup_restore_preserves_meaningful_records_and_encrypted_blobs(tmp_path: Path) -> None:
    db = tmp_path / "runtime.sqlite"
    storage_root = tmp_path / "documents"
    storage = _storage(storage_root)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        init_db(conn)
        raw_ref, _ = _seed(conn, storage)
        conn.commit()

    backup_dir = tmp_path / "backup"
    result = create_backup(db, storage_root, backup_dir)
    assert result["verified"] is True
    assert result["record_counts"]["transactions"] == 1
    assert verify_backup(backup_dir)["blob_count"] == 2

    restored_db = tmp_path / "restore" / "runtime.sqlite"
    restored_storage = tmp_path / "restore" / "documents"
    restore_backup(backup_dir, restored_db, restored_storage)
    with sqlite3.connect(restored_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    restored_provider = _storage(restored_storage)
    assert restored_provider.read_bytes(raw_ref) == b"raw contract"


def test_explicit_legacy_storage_migration_is_dry_run_atomic_and_idempotent(
    tmp_path: Path,
) -> None:
    db = tmp_path / "legacy.sqlite"
    root = tmp_path / "legacy-documents"
    provider = _storage(root)
    plaintext = b"legacy raw pii"
    path = root / "tx-legacy" / "doc-legacy"
    path.parent.mkdir(parents=True)
    path.write_bytes(plaintext)

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.execute(
            "INSERT INTO transactions "
            "(id,state,markdown,masked_markdown,created_at,lifecycle_version) "
            "VALUES ('tx-legacy','active','plain markdown','masked markdown',?, 'account_v2')",
            ("2026-01-01T00:00:00Z",),
        )
        conn.execute(
            """INSERT INTO contract_documents
            (id,transaction_id,version,original_filename,storage_ref,content_sha256,status,created_at)
            VALUES ('doc-legacy','tx-legacy',1,'legacy.pdf','tx-legacy/doc-legacy',?,'active',?)""",
            (hashlib.sha256(plaintext).hexdigest(), "2026-01-01T00:00:00Z"),
        )
        conn.commit()

        dry = migrate_storage(conn, provider, dry_run=True)
        assert dry.markdown_rows_found == 1 and dry.legacy_blobs_encrypted == 0
        assert path.read_bytes() == plaintext

        executed = migrate_storage(conn, provider, dry_run=False)
        conn.commit()
        assert executed.legacy_blobs_encrypted == 1
        assert plaintext not in path.read_bytes()
        assert provider.read_bytes("tx-legacy/doc-legacy") == plaintext
        row = conn.execute(
            "SELECT markdown,masked_markdown,markdown_storage_ref,masked_markdown_storage_ref "
            "FROM transactions WHERE id='tx-legacy'"
        ).fetchone()
        assert row["markdown"] is None and row["masked_markdown"] is None
        assert row["markdown_storage_ref"] and row["masked_markdown_storage_ref"]

        replay = migrate_storage(conn, provider, dry_run=False)
        assert replay.legacy_blobs_encrypted == 0
        assert replay.markdown_rows_migrated == 0
