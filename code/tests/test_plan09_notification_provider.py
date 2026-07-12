"""SMTP notification adapter contract without network access."""

from __future__ import annotations

import logging

import pytest

from backend.app.config import Settings
from backend.app.services.notifications import (
    FakeNotificationProvider,
    NotificationDeliveryError,
    SmtpNotificationProvider,
    make_notification_provider,
)


class _SmtpStub:
    instances: list["_SmtpStub"] = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args = None
        self.message = None
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def starttls(self, *, context):
        assert context is not None
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.message = message


def _settings(**overrides) -> Settings:
    defaults = dict(
        notification_provider="smtp",
        smtp_host="smtp.example.test",
        smtp_port=587,
        smtp_username="mailer",
        smtp_password="test-only-password",
        smtp_from_email="noreply@example.test",
        smtp_starttls=True,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_factory_defaults_to_fake() -> None:
    assert isinstance(make_notification_provider(Settings()), FakeNotificationProvider)


def test_smtp_adapter_uses_tls_and_never_logs_recipient_or_link(monkeypatch, caplog) -> None:
    _SmtpStub.instances.clear()
    monkeypatch.setattr("backend.app.services.notifications.smtplib.SMTP", _SmtpStub)
    provider = SmtpNotificationProvider(_settings())
    link = "https://frontend.example/reset/raw-one-time-token"

    with caplog.at_level(logging.INFO):
        result = provider.send_password_reset(
            to_email="private@example.test", reset_link=link
        )

    smtp = _SmtpStub.instances[-1]
    assert smtp.started_tls is True
    assert smtp.login_args == ("mailer", "test-only-password")
    assert link in smtp.message.get_content()
    assert result.channel == "smtp"
    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "private@example.test" not in rendered_logs
    assert link not in rendered_logs
    assert "test-only-password" not in rendered_logs


def test_smtp_configuration_and_unknown_provider_fail_closed() -> None:
    with pytest.raises(NotificationDeliveryError):
        SmtpNotificationProvider(_settings(smtp_host=""))
    with pytest.raises(NotificationDeliveryError):
        make_notification_provider(Settings(notification_provider="unknown"))
