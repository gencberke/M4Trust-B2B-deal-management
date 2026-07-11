"""`services/notifications.py` — `FakeNotificationProvider` kontrat testleri."""

from __future__ import annotations

import pytest

from backend.app.services.notifications import (
    FakeNotificationProvider,
    NotificationDeliveryError,
    NotificationResult,
)


def test_fake_provider_records_sent_invitation_without_network() -> None:
    provider = FakeNotificationProvider()
    result = provider.send_invitation(
        to_email="party@example.com", transaction_id="tx1", invite_link="/api/invitations/tok/accept"
    )
    assert isinstance(result, NotificationResult)
    assert result.delivered is True
    assert result.recipient == "party@example.com"
    assert len(provider.sent) == 1


def test_fake_provider_result_never_carries_invite_link_or_token() -> None:
    provider = FakeNotificationProvider()
    result = provider.send_invitation(
        to_email="party@example.com",
        transaction_id="tx1",
        invite_link="/api/invitations/super-secret-raw-token/accept",
    )
    assert "super-secret-raw-token" not in str(result)


def test_fake_provider_can_simulate_delivery_failure() -> None:
    provider = FakeNotificationProvider(fail_next=True)
    with pytest.raises(NotificationDeliveryError):
        provider.send_invitation(to_email="x@example.com", transaction_id="tx1", invite_link="/x")
    assert provider.sent == []


def test_fake_provider_fail_next_only_affects_one_call() -> None:
    provider = FakeNotificationProvider(fail_next=True)
    with pytest.raises(NotificationDeliveryError):
        provider.send_invitation(to_email="x@example.com", transaction_id="tx1", invite_link="/x")

    result = provider.send_invitation(to_email="y@example.com", transaction_id="tx1", invite_link="/y")
    assert result.delivered is True
