"""Audit event persistence (Plan 03 / Faz 3B — `audit_events`, migration 006).

Bağlayıcı kurallar (değişmedi, Plan 02'den donmuş):

1. Audit event, business event ile **aynı connection'da, aynı transaction'da**
   yazılır — `record()` kendi connection'ını açmaz (`sqlite3.connect` çağırmaz),
   kendi `commit()`/`rollback()`/`close()` çağırmaz. Transaction sınırı ve
   commit/rollback çağıranındır; business mutation rollback olursa audit satırı
   da rollback olur.
2. `metadata_allowlist` içinde olmayan hiçbir ek alan kabul edilmez.
3. Token, secret ve ham PII metadata'ya asla giremez (allowlist'te olsa bile
   yasak-örüntülü anahtarlar reddedilir).
4. Audit event'ler legacy `events` tablosuna sessizce yazılmaz — ayrı
   `audit_events` tablosu kullanılır (migration 006).

Ayrıntı ve gerekçe: `code/backend/app/services/AUDIT_CONTRACT.md`.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

_FORBIDDEN_KEY_MARKERS = (
    "token",
    "password",
    "secret",
    "checkkey",
    "card",
    "pan",
    "cvc",
    "cvv",
    "tckn",
    "vkn",
    "iban",
)


class DisallowedMetadataError(ValueError):
    """`metadata_allowlist`'te olmayan veya yasak-örüntülü bir anahtar verildiğinde fırlatılır."""


class InvalidAuditTargetError(ValueError):
    """`target` beklenen `"tip:id"` biçiminde değilse fırlatılır."""


@dataclass(frozen=True, slots=True)
class AuditActor:
    """`services/access_control.ActorContext`'ten bağımsız, dar audit-özel görünüm.

    Berke'nin `ActorContext`'ine bilinçli olarak bağımlı DEĞİLDİR — audit
    kontratı kendi minimal alan setini tutar. Çağıran, `ActorContext`'i kendi
    servis modülünde bu dar görünüme çevirir (örn. `AuditActor(actor_type="user",
    user_id=actor.user_id, acting_entity_id=actor.acting_entity_id,
    request_id=actor.request_id)`).
    """

    actor_type: str
    user_id: str | None = None
    acting_entity_id: str | None = None
    request_id: str | None = None


def _validate_metadata(
    metadata: Mapping[str, Any] | None, allowlist: frozenset[str]
) -> dict[str, Any]:
    if metadata is None:
        return {}
    disallowed = set(metadata) - allowlist
    if disallowed:
        raise DisallowedMetadataError(f"İzinsiz metadata alanları: {sorted(disallowed)}")
    for key in metadata:
        lowered = key.lower()
        if any(marker in lowered for marker in _FORBIDDEN_KEY_MARKERS):
            raise DisallowedMetadataError(f"Yasak metadata alanı: {key}")
    return dict(metadata)


def _parse_target(target: str) -> tuple[str, str]:
    """`"transaction:abc123"` -> `("transaction", "abc123")`."""
    if ":" not in target:
        raise InvalidAuditTargetError(
            f"target 'tip:id' biçiminde olmalı (örn. 'transaction:abc123'), alınan: {target!r}"
        )
    target_type, _, target_id = target.partition(":")
    target_type = target_type.strip()
    target_id = target_id.strip()
    if not target_type or not target_id:
        raise InvalidAuditTargetError(f"target tip veya id boş olamaz: {target!r}")
    return target_type, target_id


def record(
    conn: sqlite3.Connection,
    actor: AuditActor,
    action: str,
    target: str,
    metadata_allowlist: frozenset[str],
    *,
    metadata: Mapping[str, Any] | None = None,
    transaction_id: str | None = None,
) -> str:
    """`audit_events`'e tek satır yazar, üretilen `id`'yi döner.

    `conn` yalnız çağıranın bağlantısıdır: bu fonksiyon `sqlite3.connect`
    çağırmaz, `conn.commit()`/`conn.rollback()`/`conn.close()` çağırmaz —
    satır, çağıranın transaction'ının bir parçası olarak yazılır ve çağıranın
    commit/rollback kararına tabidir.

    `target`, `"tip:id"` biçiminde tek bir string'tir (örn.
    `"transaction:abc123"`, `"invitation:xyz"`) — `target_type`/`target_id`
    kolonlarına burada güvenli şekilde ayrıştırılır (`InvalidAuditTargetError`
    ile fail-closed). Metadata doğrulaması (allowlist + yasak-örüntü) her
    zaman INSERT'ten ÖNCE çalışır: geçersiz metadata hiçbir satır yazmadan
    reddedilir.
    """
    clean_metadata = _validate_metadata(metadata, metadata_allowlist)
    target_type, target_id = _parse_target(target)

    audit_id = uuid4().hex
    conn.execute(
        """INSERT INTO audit_events (
            id, transaction_id, actor_type, actor_user_id, acting_entity_id,
            action, target_type, target_id, request_id, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            audit_id,
            transaction_id,
            actor.actor_type,
            actor.user_id,
            actor.acting_entity_id,
            action,
            target_type,
            target_id,
            actor.request_id,
            json.dumps(clean_metadata, sort_keys=True, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return audit_id
