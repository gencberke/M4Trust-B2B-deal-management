"""M0 PaymentGateway port/domain sözleşmesinin ağsız unit testleri."""

from __future__ import annotations

from dataclasses import fields
from inspect import signature

import pytest

from backend.app.services.payments.domain import (
    CreatePoolPaymentCommand,
    MOKA_STANDARD_PROFILE,
    PaymentDetailQuery,
    ProviderOperationOutcome,
    ProviderOperationResult,
    ProviderPaymentIdentifier,
    ProviderPaymentStatus,
)
from backend.app.services.payments.ports import (
    FakePaymentGateway,
    InMemoryPaymentStore,
    PaymentGateway,
)


def _command(other_trx_code: str = "M4T-demo-U01") -> CreatePoolPaymentCommand:
    return CreatePoolPaymentCommand(
        amount_minor=250_000,
        currency="TRY",
        other_trx_code=other_trx_code,
        description="İlk sabit tranche",
    )


def test_domain_models_construct_and_identifier_requires_a_value() -> None:
    command = _command()
    identifier = ProviderPaymentIdentifier(other_trx_code=command.other_trx_code)

    assert command.amount_minor == 250_000
    assert PaymentDetailQuery(identifier=identifier).identifier == identifier
    with pytest.raises(ValueError, match="tanımlayıcısı"):
        ProviderPaymentIdentifier()


def test_moka_standard_profile_matches_the_public_pool_capabilities() -> None:
    assert MOKA_STANDARD_PROFILE.supports_pool_payment is True
    assert MOKA_STANDARD_PROFILE.supports_partial_pool_approval is False
    assert MOKA_STANDARD_PROFILE.supports_multiple_approvals_per_payment is False
    assert MOKA_STANDARD_PROFILE.supports_approval_undo is True
    assert MOKA_STANDARD_PROFILE.supports_fixed_tranches is True
    assert MOKA_STANDARD_PROFILE.supports_marketplace_subdealers is False


def test_port_has_no_capture_ratio_or_partial_approval_amount() -> None:
    assert "capture_ratio" not in {field.name for field in fields(CreatePoolPaymentCommand)}
    for method_name in (
        "create_pool_payment",
        "approve_pool_payment",
        "undo_pool_approval",
        "get_payment_detail",
    ):
        assert "capture_ratio" not in signature(getattr(PaymentGateway, method_name)).parameters
        assert "amount" not in signature(getattr(PaymentGateway, method_name)).parameters


def test_provider_operation_result_can_represent_an_unknown_outcome() -> None:
    identifier = ProviderPaymentIdentifier(other_trx_code="M4T-timeout-U01")
    result = ProviderOperationResult(
        outcome=ProviderOperationOutcome.UNKNOWN,
        identifier=identifier,
        provider_code="TRANSPORT_TIMEOUT",
    )

    assert result.outcome is ProviderOperationOutcome.UNKNOWN
    assert result.identifier == identifier


def test_fake_gateway_is_a_payment_gateway_and_approves_only_once() -> None:
    gateway = FakePaymentGateway()
    assert isinstance(gateway, PaymentGateway)

    created = gateway.create_pool_payment(_command())
    assert created.outcome is ProviderOperationOutcome.SUCCESS
    assert created.payment is not None

    identifier = created.payment.identifier
    assert gateway.approve_pool_payment(identifier).outcome is ProviderOperationOutcome.SUCCESS
    duplicate = gateway.approve_pool_payment(identifier)

    assert duplicate.outcome is ProviderOperationOutcome.FAILED
    assert duplicate.provider_code == "PAYMENT_ALREADY_APPROVED"
    detail = gateway.get_payment_detail(PaymentDetailQuery(identifier=identifier))
    assert detail.payment is not None
    assert detail.payment.status is ProviderPaymentStatus.APPROVED


def test_fake_gateway_is_deterministic_and_its_store_can_be_shared() -> None:
    store = InMemoryPaymentStore()
    first_gateway = FakePaymentGateway(store)
    second_gateway = FakePaymentGateway(store)

    first = first_gateway.create_pool_payment(_command("M4T-shared-U01"))
    repeated = second_gateway.create_pool_payment(_command("M4T-shared-U01"))
    assert first.payment is not None
    assert repeated.payment is not None
    assert repeated.payment.identifier == first.payment.identifier

    detail = second_gateway.get_payment_detail(
        PaymentDetailQuery(identifier=first.payment.identifier)
    )
    assert detail.outcome is ProviderOperationOutcome.SUCCESS
    assert detail.payment == first.payment
