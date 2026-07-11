"""`LocalDocumentStorageProvider` testleri (Plan 04 / Faz 4A, §4/§15)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.app.services.document_storage import (
    DocumentStorageConflictError,
    DocumentStorageIntegrityError,
    DocumentStorageInvalidReferenceError,
    LocalDocumentStorageProvider,
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _provider(tmp_path: Path) -> LocalDocumentStorageProvider:
    return LocalDocumentStorageProvider(root=tmp_path / "documents")


def test_store_and_read_round_trip(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    content = b"contract bytes"
    stored = provider.store(
        transaction_id="tx1",
        document_id="doc1",
        original_filename="sozlesme.pdf",
        media_type="application/pdf",
        content=content,
        expected_sha256=_sha256(content),
    )
    assert stored.content_sha256 == _sha256(content)
    assert stored.size_bytes == len(content)
    assert provider.read_bytes(stored.storage_ref) == content


def test_hash_mismatch_is_rejected_before_write(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    with pytest.raises(DocumentStorageIntegrityError):
        provider.store(
            transaction_id="tx1",
            document_id="doc1",
            original_filename="sozlesme.pdf",
            media_type=None,
            content=b"contract bytes",
            expected_sha256="0" * 64,
        )
    assert not (tmp_path / "documents" / "tx1" / "doc1").exists()


def test_same_ref_same_content_is_idempotent(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    content = b"contract bytes"
    first = provider.store(
        transaction_id="tx1",
        document_id="doc1",
        original_filename="a.pdf",
        media_type=None,
        content=content,
        expected_sha256=_sha256(content),
    )
    second = provider.store(
        transaction_id="tx1",
        document_id="doc1",
        original_filename="a.pdf",
        media_type=None,
        content=content,
        expected_sha256=_sha256(content),
    )
    assert first == second


def test_same_ref_different_content_is_rejected(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    provider.store(
        transaction_id="tx1",
        document_id="doc1",
        original_filename="a.pdf",
        media_type=None,
        content=b"version one",
        expected_sha256=_sha256(b"version one"),
    )
    with pytest.raises(DocumentStorageConflictError):
        provider.store(
            transaction_id="tx1",
            document_id="doc1",
            original_filename="a.pdf",
            media_type=None,
            content=b"version two",
            expected_sha256=_sha256(b"version two"),
        )
    # orijinal içerik korunur (overwrite edilmedi)
    stored_ref = "tx1/doc1"
    assert provider.read_bytes(stored_ref) == b"version one"


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "..", "", "a\\b"])
def test_traversal_ids_are_rejected(tmp_path: Path, bad_id: str) -> None:
    provider = _provider(tmp_path)
    with pytest.raises(DocumentStorageInvalidReferenceError):
        provider.store(
            transaction_id=bad_id,
            document_id="doc1",
            original_filename="a.pdf",
            media_type=None,
            content=b"x",
            expected_sha256=_sha256(b"x"),
        )


def test_original_filename_is_never_used_as_path(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    content = b"x"
    stored = provider.store(
        transaction_id="tx1",
        document_id="doc1",
        original_filename="../../etc/passwd",
        media_type=None,
        content=content,
        expected_sha256=_sha256(content),
    )
    assert stored.storage_ref == "tx1/doc1"
    assert not (tmp_path / "etc").exists()


def test_read_bytes_rejects_traversal_ref(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    with pytest.raises(DocumentStorageInvalidReferenceError):
        provider.read_bytes("../outside")


def test_delete_is_idempotent(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    content = b"x"
    stored = provider.store(
        transaction_id="tx1",
        document_id="doc1",
        original_filename="a.pdf",
        media_type=None,
        content=content,
        expected_sha256=_sha256(content),
    )
    provider.delete(stored.storage_ref)
    assert not (tmp_path / "documents" / "tx1" / "doc1").exists()
    provider.delete(stored.storage_ref)  # ikinci silme hata vermez (idempotent)


def test_atomic_write_leaves_no_temp_files_on_success(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    content = b"x" * 1000
    provider.store(
        transaction_id="tx1",
        document_id="doc1",
        original_filename="a.pdf",
        media_type=None,
        content=content,
        expected_sha256=_sha256(content),
    )
    leftovers = list((tmp_path / "documents" / "tx1").glob(".tmp-*"))
    assert leftovers == []


def test_runtime_documents_directory_is_gitignored() -> None:
    root = Path(__file__).parents[2]
    gitignore = (root / ".gitignore").read_text()
    assert "code/data/runtime/" in gitignore
