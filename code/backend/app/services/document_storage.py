"""DocumentStorageProvider — encrypted, provider-bağımsız doküman depolama.

Local adapter her blob'u AES-256-GCM ile şifreler. Anahtar yalnız
``APP_ENCRYPTION_KEY``'den gelir; eksik/yanlış anahtar, bozuk ciphertext ve
eski plaintext bloblar fail-closed davranır. Sözleşme:

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

import base64
import hashlib
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.config import Settings

_AES_KEY_BYTES = 32
_AES_NONCE_BYTES = 12
_ENVELOPE_MAGIC = b"M4TDS\x01"


class DocumentStorageError(Exception):
    """Doküman depolama katmanındaki tüm hataların ortak üst sınıfı."""


class DocumentStorageIntegrityError(DocumentStorageError):
    """Yazılan byte'ların hash'i `expected_sha256` ile eşleşmedi (fail-closed)."""


class DocumentStorageConflictError(DocumentStorageError):
    """Aynı `storage_ref` farklı içerikle yeniden yazılmaya çalışıldı (immutable)."""


class DocumentStorageInvalidReferenceError(DocumentStorageError):
    """`transaction_id`/`document_id`/`storage_ref` path traversal'a izin verecek biçimde."""


class DocumentStorageKeyError(DocumentStorageError):
    """Storage encryption key eksik veya biçimsiz (fail-closed)."""


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


def _decode_encryption_key(raw_base64: str) -> bytes:
    if not raw_base64:
        raise DocumentStorageKeyError(
            "APP_ENCRYPTION_KEY tanımlı değil; encrypted document storage açılamaz."
        )
    try:
        key = base64.b64decode(raw_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise DocumentStorageKeyError(
            "APP_ENCRYPTION_KEY geçerli base64 olmalıdır."
        ) from exc
    if len(key) != _AES_KEY_BYTES:
        raise DocumentStorageKeyError(
            "APP_ENCRYPTION_KEY 32 byte (AES-256) olmalıdır."
        )
    return key


class LocalDocumentStorageProvider:
    """Filesystem tabanlı AES-256-GCM encrypted storage adapter'ı."""

    def __init__(self, root: Path, *, encryption_key: str):
        self._root = root.resolve()
        self._key = _decode_encryption_key(encryption_key)

    def _encrypt(self, content: bytes, *, storage_ref: str) -> bytes:
        nonce = secrets.token_bytes(_AES_NONCE_BYTES)
        ciphertext = AESGCM(self._key).encrypt(
            nonce, content, storage_ref.encode("utf-8")
        )
        return _ENVELOPE_MAGIC + nonce + ciphertext

    def _decrypt(self, blob: bytes, *, storage_ref: str) -> bytes:
        minimum_length = len(_ENVELOPE_MAGIC) + _AES_NONCE_BYTES + 16
        if len(blob) < minimum_length or not blob.startswith(_ENVELOPE_MAGIC):
            raise DocumentStorageIntegrityError(
                "Encrypted storage envelope geçersiz; legacy plaintext migration gerekir."
            )
        nonce_offset = len(_ENVELOPE_MAGIC)
        nonce = blob[nonce_offset : nonce_offset + _AES_NONCE_BYTES]
        ciphertext = blob[nonce_offset + _AES_NONCE_BYTES :]
        try:
            return AESGCM(self._key).decrypt(
                nonce, ciphertext, storage_ref.encode("utf-8")
            )
        except (InvalidTag, ValueError) as exc:
            raise DocumentStorageIntegrityError(
                "Encrypted document doğrulanamadı (anahtar veya ciphertext geçersiz)."
            ) from exc

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
        encrypted = self._encrypt(content, storage_ref=storage_ref)

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
                tmp_file.write(encrypted)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            try:
                os.link(tmp_name, final_path)
            except FileExistsError:
                existing = self._decrypt(
                    final_path.read_bytes(), storage_ref=storage_ref
                )
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
        blob = self._resolve_existing(storage_ref).read_bytes()
        return self._decrypt(blob, storage_ref=storage_ref)

    def delete(self, storage_ref: str) -> None:
        self._resolve_existing(storage_ref).unlink(missing_ok=True)

    def migrate_legacy_plaintext(
        self, storage_ref: str, *, expected_sha256: str
    ) -> bool:
        """Explicit offline migration; normal ``read_bytes`` stays fail-closed.

        Returns ``True`` only when a plaintext blob was atomically replaced.
        Existing encrypted blobs are verified and treated idempotently.
        """

        path = self._resolve_existing(storage_ref)
        blob = path.read_bytes()
        if blob.startswith(_ENVELOPE_MAGIC):
            plaintext = self._decrypt(blob, storage_ref=storage_ref)
            if hashlib.sha256(plaintext).hexdigest() != expected_sha256:
                raise DocumentStorageIntegrityError(
                    "Encrypted document hash beklenen değerle eşleşmiyor."
                )
            return False
        if hashlib.sha256(blob).hexdigest() != expected_sha256:
            raise DocumentStorageIntegrityError(
                "Legacy plaintext document hash beklenen değerle eşleşmiyor."
            )
        encrypted = self._encrypt(blob, storage_ref=storage_ref)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-migrate-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            Path(tmp_name).unlink(missing_ok=True)
        return True


def make_document_storage_provider(settings: Settings) -> DocumentStorageProvider:
    """§3 adapter seçimi — local adapter daima encrypted ve fail-closed'dur."""
    return LocalDocumentStorageProvider(
        root=settings.document_storage_dir,
        encryption_key=settings.app_encryption_key,
    )
