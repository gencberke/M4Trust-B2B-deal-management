"""Upload bounds, durable job creation, and encrypted raw-document persistence."""

from __future__ import annotations

import asyncio
import hashlib
import io

import pytest

from backend.app.config import Settings
from backend.app.db import connect
from backend.app.repositories import processing_jobs as jobs_repo
from backend.app.services.document_storage import make_document_storage_provider
from backend.app.services.transaction_pipeline import LegacyPipelineInput, run_pipeline
from backend.app.services.upload_limits import (
    EmptyUploadError,
    UploadTooLargeError,
    read_upload_bounded,
)


class _RecordingUpload:
    def __init__(self, content: bytes):
        self._stream = io.BytesIO(content)
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        assert size > 0, "upload helper must never use an unbounded read"
        return self._stream.read(size)


def test_bounded_reader_never_uses_unbounded_read_and_accepts_exact_limit() -> None:
    upload = _RecordingUpload(b"12345")
    result = asyncio.run(read_upload_bounded(upload, max_bytes=5))  # type: ignore[arg-type]
    assert result == b"12345"
    assert upload.read_sizes and all(size > 0 for size in upload.read_sizes)


def test_bounded_reader_rejects_overflow_and_empty_content() -> None:
    with pytest.raises(UploadTooLargeError):
        asyncio.run(
            read_upload_bounded(_RecordingUpload(b"123456"), max_bytes=5)  # type: ignore[arg-type]
        )
    with pytest.raises(EmptyUploadError):
        asyncio.run(
            read_upload_bounded(_RecordingUpload(b""), max_bytes=5)  # type: ignore[arg-type]
        )


def test_contract_upload_limit_rejects_before_database_or_storage_write(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("MAX_CONTRACT_UPLOAD_BYTES", "4")
    conn = connect()
    try:
        before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    finally:
        conn.close()

    response = client.post(
        "/api/transactions",
        files={"file": ("contract.md", io.BytesIO(b"12345"), "text/markdown")},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "CONTRACT_FILE_TOO_LARGE"
    conn = connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == before
    finally:
        conn.close()
    assert not any((tmp_path / "documents").rglob("*"))


def test_legacy_raw_upload_is_encrypted_and_has_a_durable_extraction_job(client) -> None:
    plaintext = b"legacy contract text that must not be stored in plaintext"
    response = client.post(
        "/api/transactions",
        files={"file": ("contract.md", io.BytesIO(plaintext), "text/markdown")},
    )
    assert response.status_code == 200, response.text
    transaction_id = response.json()["id"]

    conn = connect()
    try:
        document = conn.execute(
            "SELECT storage_ref, content_sha256 FROM contract_documents "
            "WHERE transaction_id = ? ORDER BY version LIMIT 1",
            (transaction_id,),
        ).fetchone()
        job = jobs_repo.get_by_idempotency(
            conn,
            kind="extraction",
            idempotency_key=f"extraction:transaction:{transaction_id}",
        )
    finally:
        conn.close()
    assert document is not None
    assert document["content_sha256"] == hashlib.sha256(plaintext).hexdigest()
    assert job is not None and job["status"] == "succeeded"

    settings = Settings.from_env()
    storage = make_document_storage_provider(settings)
    assert storage.read_bytes(document["storage_ref"]) == plaintext
    encrypted_path = settings.document_storage_dir / document["storage_ref"]
    assert plaintext not in encrypted_path.read_bytes()


def test_storage_read_failure_is_captured_by_job_and_transaction_guards(client) -> None:
    response = client.post(
        "/api/transactions",
        files={"file": ("contract.md", io.BytesIO(b"recoverable input"), "text/markdown")},
    )
    transaction_id = response.json()["id"]
    settings = Settings.from_env()
    storage = make_document_storage_provider(settings)

    conn = connect()
    try:
        document = conn.execute(
            "SELECT storage_ref FROM contract_documents WHERE transaction_id = ?",
            (transaction_id,),
        ).fetchone()
        job = jobs_repo.get_by_idempotency(
            conn,
            kind="extraction",
            idempotency_key=f"extraction:transaction:{transaction_id}",
        )
        jobs_repo.mark_retry_pending(conn, job["id"], reason_code="TEST_STORAGE_READ")
        conn.execute(
            "UPDATE transactions SET state = 'extracting' WHERE id = ?", (transaction_id,)
        )
        conn.commit()
    finally:
        conn.close()
    storage.delete(document["storage_ref"])

    run_pipeline(
        transaction_id,
        True,
        settings,
        LegacyPipelineInput(storage_ref=document["storage_ref"], suffix=".md"),
    )

    conn = connect()
    try:
        refreshed_job = jobs_repo.get_by_id(conn, job["id"])
        state = conn.execute(
            "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
        ).fetchone()["state"]
        event_payload = conn.execute(
            "SELECT payload FROM events WHERE transaction_id = ? ORDER BY created_at DESC LIMIT 1",
            (transaction_id,),
        ).fetchone()["payload"]
    finally:
        conn.close()
    assert refreshed_job["status"] == "failed"
    assert refreshed_job["last_error_code"] == "PIPELINE_ERROR"
    assert state == "awaiting_review"
    assert document["storage_ref"] not in event_payload
