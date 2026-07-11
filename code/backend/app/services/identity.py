"""Legal entity + membership servisi — TCKN/VKN şifreleme dahil (Faz 3A).

Ham tax identifier hiçbir response/log/event/exception içine girmez. Şifreleme
AES-256-GCM (her çağrıda random nonce → aynı numara farklı ciphertext üretir);
arama HMAC-SHA256 ile deterministik `tax_identifier_lookup_hmac` üzerinden
yapılır. Anahtarlar yalnız `Settings.app_encryption_key`/`app_hmac_key`'den
gelir — insecure sabit fallback YOKTUR.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timezone
from sqlite3 import Connection, Row

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.api.errors import ApiError
from backend.app.config import Settings
from backend.app.repositories import entities as entities_repo

_AES_KEY_BYTES = 32
_AES_NONCE_BYTES = 12
_LAST4_LENGTH = 4


class KeyConfigurationError(RuntimeError):
    """`APP_ENCRYPTION_KEY`/`APP_HMAC_KEY` eksik veya biçimsiz."""


def _decode_key(raw_base64: str, *, env_name: str) -> bytes:
    if not raw_base64:
        raise KeyConfigurationError(
            f"{env_name} tanımlı değil. Legal entity işlemleri için gereklidir."
        )
    try:
        return base64.b64decode(raw_base64, validate=True)
    except Exception as exc:  # noqa: BLE001 — biçim hatasını tek noktada normalize eder
        raise KeyConfigurationError(f"{env_name} geçerli bir base64 değeri değil.") from exc


def _encryption_key(settings: Settings) -> bytes:
    key = _decode_key(settings.app_encryption_key, env_name="APP_ENCRYPTION_KEY")
    if len(key) != _AES_KEY_BYTES:
        raise KeyConfigurationError("APP_ENCRYPTION_KEY 32 byte (AES-256) olmalıdır.")
    return key


def _hmac_key(settings: Settings) -> bytes:
    return _decode_key(settings.app_hmac_key, env_name="APP_HMAC_KEY")


def normalize_tax_identifier(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def encrypt_tax_identifier(normalized_identifier: str, *, settings: Settings) -> str:
    """Nonce + ciphertext'i base64 tek string olarak döner (DB'de TEXT kolon)."""

    key = _encryption_key(settings)
    nonce = secrets.token_bytes(_AES_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, normalized_identifier.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_tax_identifier(ciphertext_b64: str, *, settings: Settings) -> str:
    key = _encryption_key(settings)
    raw = base64.b64decode(ciphertext_b64)
    nonce, ciphertext = raw[:_AES_NONCE_BYTES], raw[_AES_NONCE_BYTES:]
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


def tax_identifier_lookup_hmac(normalized_identifier: str, *, settings: Settings) -> str:
    key = _hmac_key(settings)
    return hmac.new(key, normalized_identifier.encode("utf-8"), hashlib.sha256).hexdigest()


def tax_identifier_last4(normalized_identifier: str) -> str:
    return normalized_identifier[-_LAST4_LENGTH:]


def create_entity(
    conn: Connection,
    *,
    entity_type: str,
    legal_name: str,
    tax_identifier_type: str,
    raw_tax_identifier: str,
    tax_office: str | None,
    address_json: dict | None,
    created_by_user_id: str,
    settings: Settings,
) -> str:
    normalized = normalize_tax_identifier(raw_tax_identifier)
    entity_id = entities_repo.insert_entity(
        conn,
        entity_type=entity_type,
        legal_name=legal_name,
        tax_identifier_type=tax_identifier_type,
        tax_identifier_ciphertext=encrypt_tax_identifier(normalized, settings=settings),
        tax_identifier_lookup_hmac=tax_identifier_lookup_hmac(normalized, settings=settings),
        tax_identifier_last4=tax_identifier_last4(normalized),
        tax_office=tax_office,
        address_json=json.dumps(address_json) if address_json is not None else None,
        verification_status="self_declared",
        created_by_user_id=created_by_user_id,
        now=_now(),
    )
    entities_repo.insert_membership(
        conn, user_id=created_by_user_id, legal_entity_id=entity_id, role="owner", now=_now()
    )
    return entity_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_membership(conn: Connection, *, user_id: str, entity_id: str) -> Row:
    """Entity'ye erişimi doğrular; yoksa varlığı sızdırmayan 404 döner."""

    membership = entities_repo.get_active_membership(
        conn, user_id=user_id, legal_entity_id=entity_id
    )
    if membership is None:
        raise ApiError(
            status_code=404, code="ENTITY_NOT_FOUND", message="İşletme bulunamadı."
        )
    return membership


def require_write_role(membership: Row) -> None:
    if membership["role"] not in ("owner", "admin"):
        raise ApiError(
            status_code=403,
            code="ENTITY_ROLE_FORBIDDEN",
            message="Bu işlem için owner veya admin rolü gerekir.",
        )


def update_entity(
    conn: Connection,
    *,
    entity_id: str,
    legal_name: str | None,
    tax_office: str | None,
    address_json_provided: bool,
    address_json: dict | None,
) -> None:
    fields: dict[str, object] = {}
    if legal_name is not None:
        fields["legal_name"] = legal_name
    if tax_office is not None:
        fields["tax_office"] = tax_office
    if address_json_provided:
        fields["address_json"] = json.dumps(address_json) if address_json is not None else None
    entities_repo.update_entity_fields(conn, entity_id=entity_id, fields=fields, now=_now())
