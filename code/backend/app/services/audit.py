"""Audit event kontrat iskeleti (Plan 02 / Faz 2B).

`audit_events` tablosu burada YOKTUR — migration `006` Plan 03'e aittir. Bu
modül yalnız donmuş **imzayı** ve **kuralları** tanımlar; INSERT gövdesi Plan
03'te eklenene kadar `record()` bilinçli olarak `NotImplementedError` fırlatır.

Bağlayıcı kurallar:

1. Audit event, business event ile **aynı connection'da, aynı transaction'da**
   yazılır — `record()` kendi connection'ını açmaz (`sqlite3.connect` çağırmaz).
2. `record()` kendi commit/rollback'ini yapmaz; transaction sınırı çağıranındır.
3. `metadata_allowlist` içinde olmayan hiçbir anahtar kabul edilmez — rastgele
   metadata yazılamaz.
4. Token, secret ve ham PII (kart verisi, TCKN/VKN, IBAN, tam ad/adres) hiçbir
   koşulda metadata'ya giremez; anahtar adı bu kalıplardan birini içeriyorsa
   allowlist'te olsa bile reddedilir (savunma derinliği).
5. Audit event'ler legacy `events` tablosuna **sessizce yazılmaz** — ayrı bir
   `audit_events` tablosu gerekir (Plan 03).

Ayrıntı ve gerekçe: `code/backend/app/services/AUDIT_CONTRACT.md`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True, slots=True)
class AuditActor:
    """`services/access_control.ActorContext`'ten bağımsız, dar audit-özel görünüm.

    Berke'nin `ActorContext`'ine bilinçli olarak bağımlı DEĞİLDİR — audit
    kontratı, actor kontratının iç temsilinden çapraz-yazarlıkla etkilenmemesi
    için kendi minimal alan setini tutar (yalnız `actor_type`/`user_id`/
    `acting_entity_id`; audit'e girmemesi gereken alanlar zaten yoktur).
    """

    actor_type: str
    user_id: str | None = None
    acting_entity_id: str | None = None


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


def record(
    conn: sqlite3.Connection,
    actor: AuditActor,
    action: str,
    target: str,
    metadata_allowlist: frozenset[str],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Audit event kontrat imzası — gövde Plan 03'te (migration 006 sonrası) dolar.

    `conn` yalnız çağıranın bağlantısıdır; bu fonksiyon `sqlite3.connect`
    çağırmaz, `conn.commit()`/`conn.rollback()` çağırmaz, `conn` üzerinde
    hiçbir I/O yapmaz — metadata doğrulaması DB'den bağımsızdır ve tabloya
    yazım henüz yoktur.
    """
    _validate_metadata(metadata, metadata_allowlist)
    raise NotImplementedError(
        "audit_events tablosu henüz yok (migration 006, Plan 03); kontrat şimdilik iskelettir."
    )
