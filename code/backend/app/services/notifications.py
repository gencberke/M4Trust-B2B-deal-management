"""NotificationProvider port + fake adapter (Plan 03 / Faz 3B).

Adapter+fake ilkesi (ARCHITECTURE §3, AGENTS.md): dış bildirim kanalı (e-posta/
SMS) bir port arkasına saklanır, seçim env ile yapılır, demo/test için ağa
çıkmayan bir fake her zaman vardır. Bu fazda yalnız fake implement edilir;
gerçek e-posta sağlayıcısı kapsam dışıdır.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NotificationResult:
    """Gönderim sonucunun test/demo-güvenli özeti — raw token TAŞIMAZ."""

    delivered: bool
    channel: str
    recipient: str


class NotificationProvider(Protocol):
    """Invitation bildirimi göndermek için provider-bağımsız port."""

    def send_invitation(
        self, *, to_email: str, transaction_id: str, invite_link: str
    ) -> NotificationResult:
        """`invite_link` raw token içerebilir (tek seferlik) -- provider bunu
        yalnız ilgili kanala (e-posta gövdesi vb.) taşır; kalıcı loga yazmaz."""
        ...


@dataclass
class FakeNotificationProvider:
    """Ağa çıkmayan, demo/test-güvenli `NotificationProvider`.

    Gönderilen invitation'ları bellekte tutar (yalnız test/demo gözlemi
    için) -- `invite_link` (raw token içerebilir) hiçbir kalıcı log satırına
    yazılmaz, yalnız bu process-local listede durur.
    """

    sent: list[NotificationResult] = field(default_factory=list)
    fail_next: bool = False

    def send_invitation(
        self, *, to_email: str, transaction_id: str, invite_link: str
    ) -> NotificationResult:
        if self.fail_next:
            self.fail_next = False
            raise NotificationDeliveryError(
                f"Fake provider: {to_email} adresine gönderim başarısız (test)."
            )
        logger.info(
            "invitation bildirimi (fake): transaction=%s alici=%s", transaction_id, to_email
        )
        result = NotificationResult(delivered=True, channel="fake", recipient=to_email)
        self.sent.append(result)
        return result


class NotificationDeliveryError(RuntimeError):
    """Provider gönderim yapamadığında fırlatılır.

    Çağıran (services/invitations.py), bu hatayı invitation DB satırının
    zaten yazıldığı bir transaction içinde yakalayabilir; provider hatası
    business mutation'ı yarım/belirsiz bırakmamalıdır (invitation her zaman
    tutarlı bir `pending` satır olarak kalır, yalnız bildirim başarısız olur).
    """
