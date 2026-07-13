"""Explicit pre-Plan-09 plaintext-to-encrypted storage migration."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from sqlite3 import Connection

from backend.app.services.document_storage import LocalDocumentStorageProvider


@dataclass(frozen=True, slots=True)
class StorageMigrationResult:
    legacy_blobs_found: int
    legacy_blobs_encrypted: int
    markdown_rows_found: int
    markdown_rows_migrated: int
    dry_run: bool

    def as_safe_dict(self) -> dict:
        return asdict(self)


def migrate_storage(
    conn: Connection,
    storage: LocalDocumentStorageProvider,
    *,
    dry_run: bool,
) -> StorageMigrationResult:
    blob_rows: dict[str, str] = {}
    for row in conn.execute(
        "SELECT storage_ref,content_sha256 FROM contract_documents "
        "WHERE retention_deleted_at IS NULL ORDER BY storage_ref"
    ):
        blob_rows[row["storage_ref"]] = row["content_sha256"]
    for row in conn.execute(
        "SELECT storage_ref,file_sha256 FROM evidence_records "
        "WHERE storage_ref IS NOT NULL AND file_sha256 IS NOT NULL "
        "AND retention_deleted_at IS NULL ORDER BY storage_ref"
    ):
        blob_rows[row["storage_ref"]] = row["file_sha256"]

    markdown_rows = conn.execute(
        "SELECT id,markdown,masked_markdown,markdown_storage_ref,masked_markdown_storage_ref "
        "FROM transactions WHERE "
        "(markdown IS NOT NULL AND markdown_storage_ref IS NULL) OR "
        "(masked_markdown IS NOT NULL AND masked_markdown_storage_ref IS NULL) "
        "ORDER BY id"
    ).fetchall()
    if dry_run:
        return StorageMigrationResult(
            legacy_blobs_found=len(blob_rows),
            legacy_blobs_encrypted=0,
            markdown_rows_found=len(markdown_rows),
            markdown_rows_migrated=0,
            dry_run=True,
        )

    encrypted = 0
    for storage_ref, expected_hash in blob_rows.items():
        if storage.migrate_legacy_plaintext(
            storage_ref, expected_sha256=expected_hash
        ):
            encrypted += 1

    migrated_rows = 0
    for row in markdown_rows:
        updates: dict[str, object] = {}
        if row["markdown"] is not None and row["markdown_storage_ref"] is None:
            content = row["markdown"].encode("utf-8")
            stored = storage.store(
                transaction_id=row["id"],
                document_id="migrated-markdown-v1",
                original_filename="normalized-markdown.txt",
                media_type="text/markdown",
                content=content,
                expected_sha256=hashlib.sha256(content).hexdigest(),
            )
            updates["markdown_storage_ref"] = stored.storage_ref
        if row["masked_markdown"] is not None and row["masked_markdown_storage_ref"] is None:
            content = row["masked_markdown"].encode("utf-8")
            stored = storage.store(
                transaction_id=row["id"],
                document_id="migrated-masked-markdown-v1",
                original_filename="masked-markdown.txt",
                media_type="text/markdown",
                content=content,
                expected_sha256=hashlib.sha256(content).hexdigest(),
            )
            updates["masked_markdown_storage_ref"] = stored.storage_ref
        if updates:
            conn.execute(
                "UPDATE transactions SET markdown=NULL, masked_markdown=NULL, "
                "markdown_storage_ref=COALESCE(?,markdown_storage_ref), "
                "masked_markdown_storage_ref=COALESCE(?,masked_markdown_storage_ref) "
                "WHERE id=?",
                (
                    updates.get("markdown_storage_ref"),
                    updates.get("masked_markdown_storage_ref"),
                    row["id"],
                ),
            )
            migrated_rows += 1

    return StorageMigrationResult(
        legacy_blobs_found=len(blob_rows),
        legacy_blobs_encrypted=encrypted,
        markdown_rows_found=len(markdown_rows),
        markdown_rows_migrated=migrated_rows,
        dry_run=False,
    )
