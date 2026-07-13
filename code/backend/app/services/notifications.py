"""Notification port plus fake and TLS-capable SMTP adapters."""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from backend.app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NotificationResult:
    """Delivery summary; raw tokens are never represented."""

    delivered: bool
    channel: str
    recipient: str


class NotificationProvider(Protocol):
    def send_invitation(
        self, *, to_email: str, transaction_id: str, invite_link: str
    ) -> NotificationResult: ...

    def send_password_reset(self, *, to_email: str, reset_link: str) -> NotificationResult: ...

    def send_email_verification(
        self, *, to_email: str, verification_link: str
    ) -> NotificationResult: ...


class NotificationDeliveryError(RuntimeError):
    """A safe provider/configuration failure without recipient or raw-link detail."""


@dataclass
class FakeNotificationProvider:
    """Network-free test/demo adapter; raw links remain process-local only."""

    sent: list[NotificationResult] = field(default_factory=list)
    delivery_links: list[str] = field(default_factory=list, repr=False)
    fail_next: bool = False

    def send_invitation(
        self, *, to_email: str, transaction_id: str, invite_link: str
    ) -> NotificationResult:
        if self.fail_next:
            self.fail_next = False
            raise NotificationDeliveryError("Fake notification delivery failed.")
        logger.info(
            "invitation notification accepted",
            extra={
                "event": "notification_accepted",
                "action": "send_invitation",
                "outcome": "success",
            },
        )
        result = NotificationResult(delivered=True, channel="fake", recipient=to_email)
        self.sent.append(result)
        return result

    def _send_auth_link(
        self, *, to_email: str, link: str, action: str
    ) -> NotificationResult:
        if self.fail_next:
            self.fail_next = False
            raise NotificationDeliveryError("Fake notification delivery failed.")
        logger.info(
            "auth notification accepted",
            extra={
                "event": "notification_accepted",
                "action": action,
                "outcome": "success",
            },
        )
        result = NotificationResult(delivered=True, channel="fake", recipient=to_email)
        self.sent.append(result)
        self.delivery_links.append(link)
        return result

    def send_password_reset(self, *, to_email: str, reset_link: str) -> NotificationResult:
        return self._send_auth_link(
            to_email=to_email, link=reset_link, action="send_auth_reset"
        )

    def send_email_verification(
        self, *, to_email: str, verification_link: str
    ) -> NotificationResult:
        return self._send_auth_link(
            to_email=to_email, link=verification_link, action="send_email_verification"
        )


class SmtpNotificationProvider:
    """Minimal SMTP adapter; message bodies carry links but logs never do."""

    def __init__(self, settings: Settings):
        if not settings.smtp_host or not settings.smtp_from_email:
            raise NotificationDeliveryError("SMTP notification configuration is incomplete.")
        self._settings = settings

    def _send(self, *, to_email: str, subject: str, body: str, action: str) -> NotificationResult:
        message = EmailMessage()
        message["From"] = self._settings.smtp_from_email
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(
                self._settings.smtp_host,
                self._settings.smtp_port,
                timeout=self._settings.smtp_timeout_seconds,
            ) as client:
                if self._settings.smtp_starttls:
                    client.starttls(context=ssl.create_default_context())
                if self._settings.smtp_username:
                    client.login(
                        self._settings.smtp_username,
                        self._settings.smtp_password,
                    )
                client.send_message(message)
        except (OSError, smtplib.SMTPException):
            raise NotificationDeliveryError("SMTP notification delivery failed.") from None
        logger.info(
            "notification accepted",
            extra={
                "event": "notification_accepted",
                "action": action,
                "outcome": "success",
            },
        )
        return NotificationResult(delivered=True, channel="smtp", recipient=to_email)

    def send_invitation(
        self, *, to_email: str, transaction_id: str, invite_link: str
    ) -> NotificationResult:
        return self._send(
            to_email=to_email,
            subject="M4Trust işlem daveti",
            body=f"M4Trust işlem davetinizi açın:\n{invite_link}\n",
            action="send_invitation",
        )

    def send_password_reset(self, *, to_email: str, reset_link: str) -> NotificationResult:
        return self._send(
            to_email=to_email,
            subject="M4Trust parola sıfırlama",
            body=f"Parolanızı sıfırlamak için tek kullanımlık bağlantı:\n{reset_link}\n",
            action="send_auth_reset",
        )

    def send_email_verification(
        self, *, to_email: str, verification_link: str
    ) -> NotificationResult:
        return self._send(
            to_email=to_email,
            subject="M4Trust e-posta doğrulama",
            body=f"E-posta adresinizi doğrulayın:\n{verification_link}\n",
            action="send_email_verification",
        )


def make_notification_provider(settings: Settings | None = None) -> NotificationProvider:
    resolved = settings or Settings.from_env()
    if resolved.notification_provider == "fake":
        return FakeNotificationProvider()
    if resolved.notification_provider == "smtp":
        return SmtpNotificationProvider(resolved)
    raise NotificationDeliveryError("Unsupported notification provider configuration.")
