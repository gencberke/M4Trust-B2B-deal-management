"""DocumentStorageProvider — kalıcı, provider-bağımsız doküman depolama sözleşmesi.

Bu faz local filesystem implementasyonunu içerir; şifreleme YAPILMAZ (bilinçli
sınır, v2 §2.14 — hardening hedefi sonraki bir iştir). Sözleşme:

- `store()` bytes'ı `expected_sha256` ile eşleşmeye zorlar (fail-closed),
  atomic yazar (temp dosya + fsync + `os.replace`) ve aynı `storage_ref` için
  sessiz overwrite yapmaz — aynı ref+aynı byte idempotent, aynı ref+farklı
  byte reddedilir.
- `storage_ref`, `transaction_id`/`document_id`'den türetilir; çağıran
  idempotent upload'larda içerik hash'ini `document_id` olarak kullanabilir.
  Kullanıcı dosya adı (`original_filename`) hiçbir zaman path bileşeni olarak
  kullanılmaz — traversal mümkün değildir.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from backend.app.config import Settings


class DocumentStorageError(Exception):
    """Doküman depolama katmanındaki tüm hataların ortak üst sınıfı."""


class DocumentStorageIntegrityError(DocumentStorageError):
    """Yazılan byte'ların hash'i `expected_sha256` ile eşleşmedi (fail-closed)."""


class DocumentStorageConflictError(DocumentStorageError):
    """Aynı `storage_ref` farklı içerikle yeniden yazılmaya çalışıldı (immutable)."""


class DocumentStorageInvalidReferenceError(DocumentStorageError):
    """`transaction_id`/`document_id`/`storage_ref` path traversal'a izin verecek biçimde."""


@dataclass(frozen=True, slots=True)
class StoredDocument:
    storage_ref: str
    content_sha256: str
    size_bytes: int


class DocumentStorageProvider(Protocol):
    def store(
        self,
        *,
        transaction_id: str,
        document_id: str,
        original_filename: str,
        media_type: str | None,
        content: bytes,
        expected_sha256: str,
    ) -> StoredDocument: ...

    def read_bytes(self, storage_ref: str) -> bytes: ...

    def delete(self, storage_ref: str) -> None: ...


def _validate_id_component(name: str, *, label: str) -> None:
    """`transaction_id`/`document_id` path bileşeni olarak güvenli mi?

    Yalnızca çağıranın kendi ürettiği UUID hex string'leri beklenir; yine de
    savunma amaçlı ayraç/parent-dizin karakterleri reddedilir (traversal
    mümkün değildir — spec §4).
    """
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise DocumentStorageInvalidReferenceError(f"Geçersiz {label}: {name!r}")


class LocalDocumentStorageProvider:
    """Filesystem tabanlı `DocumentStorageProvider` — şifresiz, local/demo implementasyonu."""

    def __init__(self, root: Path):
        self._root = root.resolve()

    def _final_path(self, transaction_id: str, document_id: str) -> tuple[str, Path]:
        _validate_id_component(transaction_id, label="transaction_id")
        _validate_id_component(document_id, label="document_id")
        storage_ref = f"{transaction_id}/{document_id}"
        return storage_ref, self._root / transaction_id / document_id

    def _resolve_existing(self, storage_ref: str) -> Path:
        parts = storage_ref.split("/")
        if len(parts) != 2:
            raise DocumentStorageInvalidReferenceError(f"Geçersiz storage_ref: {storage_ref!r}")
        transaction_id, document_id = parts
        _validate_id_component(transaction_id, label="transaction_id")
        _validate_id_component(document_id, label="document_id")
        path = (self._root / transaction_id / document_id).resolve()
        if self._root not in path.parents and path != self._root:
            raise DocumentStorageInvalidReferenceError(f"storage_ref kök dışına çıkıyor: {storage_ref!r}")
        return path

    def store(
        self,
        *,
        transaction_id: str,
        document_id: str,
        original_filename: str,
        media_type: str | None,
        content: bytes,
        expected_sha256: str,
    ) -> StoredDocument:
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != expected_sha256:
            raise DocumentStorageIntegrityError(
                f"İçerik hash'i beklenenle eşleşmedi: beklenen={expected_sha256} gerçek={actual_sha256}"
            )

        storage_ref, final_path = self._final_path(transaction_id, document_id)

        # Major 5 remediation: önceden `final_path.exists()` ön-kontrolü + koşulsuz
        # `os.replace()` kullanılıyordu -- iki concurrent farklı-içerikli yazıcı
        # ikisi de "yok" görüp ikisi de üzerine yazabiliyordu (TOCTOU), son yazan
        # sessizce kazanıyordu. `os.link()` (hard-link) OS seviyesinde atomiktir:
        # hedef zaten varsa `FileExistsError` garanti kesin/kör bir yarış olmadan
        # döner; ancak o zaman mevcut byte'lar karşılaştırılır (aynıysa idempotent,
        # farklıysa conflict).
        final_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(final_path.parent), prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as tmp_file:
                tmp_file.write(content)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            try:
                os.link(tmp_name, final_path)
            except FileExistsError:
                existing = final_path.read_bytes()
                if existing != content:
                    raise DocumentStorageConflictError(
                        f"storage_ref zaten farklı içerikle var: {storage_ref!r} (immutable)"
                    ) from None
        finally:
            Path(tmp_name).unlink(missing_ok=True)

        return StoredDocument(
            storage_ref=storage_ref, content_sha256=actual_sha256, size_bytes=len(content)
        )

    def read_bytes(self, storage_ref: str) -> bytes:
        return self._resolve_existing(storage_ref).read_bytes()

    def delete(self, storage_ref: str) -> None:
        self._resolve_existing(storage_ref).unlink(missing_ok=True)


def make_document_storage_provider(settings: Settings) -> DocumentStorageProvider:
    """§3 adapter seçimi — bu fazda tek implementasyon (`LocalDocumentStorageProvider`)."""
    return LocalDocumentStorageProvider(root=settings.document_storage_dir)
