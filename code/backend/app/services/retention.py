"""Explicit, idempotent raw-document retention cleanup (Plan 09)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from sqlite3 import Connection

from backend.app.services.document_storage import DocumentStorageProvider

_TERMINAL_STATES = frozenset({"settled", "decided", "rejected", "cancelled"})


@dataclass(frozen=True, slots=True)
class RetentionResult:
    selected: int
    eligible: int
    skipped_active: int
    blobs_planned: int
    blobs_deleted: int
    missing_blobs: int
    dry_run: bool

    def as_safe_dict(self) -> dict:
        return asdict(self)


def select_transaction_ids(
    conn: Connection,
    *,
    transaction_id: str | None = None,
    older_than_days: int | None = None,
) -> list[str]:
    """Exactly one explicit scope is required; output contains opaque IDs only."""

    if (transaction_id is None) == (older_than_days is None):
        raise ValueError("transaction_id veya older_than_days kapsamlarından tam biri gerekir")
    if transaction_id is not None:
        row = conn.execute("SELECT id FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        return [row["id"]] if row is not None else []
    if older_than_days is None or older_than_days < 0:
        raise ValueError("older_than_days sıfır veya pozitif olmalıdır")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    return [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM transactions WHERE created_at < ? ORDER BY id", (cutoff,)
        )
    ]


def cleanup_transactions(
    conn: Connection,
    storage: DocumentStorageProvider,
    transaction_ids: list[str],
    *,
    dry_run: bool,
) -> RetentionResult:
    """Delete raw/encrypted blobs only for terminal transactions.

    References are tombstoned in the same DB transaction. Missing files are
    safe/idempotent and never expose paths in the returned audit summary.
    """

    eligible: list[str] = []
    skipped_active = 0
    for transaction_id in transaction_ids:
        row = conn.execute(
            "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
        ).fetchone()
        if row is None:
            continue
        if row["state"] not in _TERMINAL_STATES:
            skipped_active += 1
            continue
        eligible.append(transaction_id)

    refs: list[tuple[str, str, str]] = []
    for transaction_id in eligible:
        tx = conn.execute(
            "SELECT markdown_storage_ref, masked_markdown_storage_ref "
            "FROM transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()
        for kind, key in (
            ("markdown", "markdown_storage_ref"),
            ("masked_markdown", "masked_markdown_storage_ref"),
        ):
            if tx is not None and tx[key]:
                refs.append((transaction_id, kind, tx[key]))
        refs.extend(
            (transaction_id, "contract_document", row["storage_ref"])
            for row in conn.execute(
                "SELECT storage_ref FROM contract_documents "
                "WHERE transaction_id = ? AND retention_deleted_at IS NULL",
                (transaction_id,),
            )
            if row["storage_ref"]
        )
        refs.extend(
            (transaction_id, "evidence", row["storage_ref"])
            for row in conn.execute(
                "SELECT storage_ref FROM evidence_records "
                "WHERE transaction_id = ? AND storage_ref IS NOT NULL "
                "AND retention_deleted_at IS NULL",
                (transaction_id,),
            )
        )

    if dry_run:
        return RetentionResult(
            selected=len(transaction_ids),
            eligible=len(eligible),
            skipped_active=skipped_active,
            blobs_planned=len(refs),
            blobs_deleted=0,
            missing_blobs=0,
            dry_run=True,
        )

    deleted = 0
    missing = 0
    now = datetime.now(timezone.utc).isoformat()
    for transaction_id, kind, storage_ref in refs:
        try:
            storage.read_bytes(storage_ref)
        except FileNotFoundError:
            missing += 1
        else:
            storage.delete(storage_ref)
            deleted += 1
        if kind in {"markdown", "masked_markdown"}:
            column = (
                "markdown_storage_ref" if kind == "markdown" else "masked_markdown_storage_ref"
            )
            conn.execute(
                f"UPDATE transactions SET {column} = NULL, markdown_deleted_at = ? WHERE id = ?",
                (now, transaction_id),
            )
        elif kind == "contract_document":
            conn.execute(
                "UPDATE contract_documents SET retention_deleted_at = ? "
                "WHERE transaction_id = ? AND storage_ref = ? AND retention_deleted_at IS NULL",
                (now, transaction_id, storage_ref),
            )
        else:
            conn.execute(
                "UPDATE evidence_records SET retention_deleted_at = ? "
                "WHERE transaction_id = ? AND storage_ref = ? AND retention_deleted_at IS NULL",
                (now, transaction_id, storage_ref),
            )

    # Legacy plaintext markdown is removed only after every encrypted ref was
    # handled/tombstoned. Immutable extraction/rule records remain audit-only
    # and are covered by the documented retention exception.
    for transaction_id in eligible:
        conn.execute(
            "UPDATE transactions SET markdown = NULL, masked_markdown = NULL, "
            "markdown_deleted_at = COALESCE(markdown_deleted_at, ?) WHERE id = ?",
            (now, transaction_id),
        )
    return RetentionResult(
        selected=len(transaction_ids),
        eligible=len(eligible),
        skipped_active=skipped_active,
        blobs_planned=len(refs),
        blobs_deleted=deleted,
        missing_blobs=missing,
        dry_run=False,
    )
