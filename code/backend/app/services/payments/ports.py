"""Payment gateway port'u ve testlerde kullanılan ağsız fake implementasyonu."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Protocol, runtime_checkable

from backend.app.services.payments.domain import (
    CreatePoolPaymentCommand,
    CreatePoolPaymentResult,
    MOKA_STANDARD_PROFILE,
    PaymentDetailQuery,
    PaymentDetailResult,
    ProviderOperationOutcome,
    ProviderOperationResult,
    ProviderPaymentDetail,
    ProviderPaymentIdentifier,
    ProviderPaymentStatus,
)


@runtime_checkable
class PaymentGateway(Protocol):
    """Moka standard profilinin desteklediği tek-atışlık pool payment port'u."""

    def create_pool_payment(self, command: CreatePoolPaymentCommand) -> CreatePoolPaymentResult:
        """Bir funding unit için pool payment oluşturur."""

    def approve_pool_payment(
        self, identifier: ProviderPaymentIdentifier
    ) -> ProviderOperationResult:
        """Bir provider ödemesini bir kez ve tam tutarla approve eder."""

    def undo_pool_approval(
        self, identifier: ProviderPaymentIdentifier
    ) -> ProviderOperationResult:
        """Açık ekstre penceresinde bir pool approval'ı geri alır."""

    def get_payment_detail(self, query: PaymentDetailQuery) -> PaymentDetailResult:
        """Reconciliation için provider ödeme detayını getirir."""


@runtime_checkable
class RefundCapableGateway(Protocol):
    """Refund contract'ı frozen gateway'e girmeden önceki opsiyonel seam.

    Exact Moka refund endpoint'i mevcut değilse production adapter bunu
    sağlamaz; payment operations fail-closed unsupported sonucu üretir.
    """

    def refund_payment(
        self, identifier: ProviderPaymentIdentifier
    ) -> ProviderOperationResult:
        """Bir funding unit'in tamamını provider'da refund eder."""


class FakePaymentStore(Protocol):
    """Fake gateway state'inin değiştirilebilir persistence sınırı.

    M0'da ``InMemoryPaymentStore`` kullanılır; 06'da aynı küçük sözleşme
    SQLite-backed store'a bağlanacaktır.
    """

    def get(self, identifier: ProviderPaymentIdentifier) -> ProviderPaymentDetail | None:
        """Tanımlayıcının işaret ettiği ödemeyi döner."""

    def save(self, payment: ProviderPaymentDetail) -> None:
        """Ödemenin son durumunu atomik store sorumluluğuyla saklar."""


class InMemoryPaymentStore:
    """Deterministik fake gateway için süreç-içi, enjekte edilebilir store."""

    def __init__(self) -> None:
        self._by_virtual_pos_order_id: dict[str, ProviderPaymentDetail] = {}
        self._by_other_trx_code: dict[str, ProviderPaymentDetail] = {}

    def get(self, identifier: ProviderPaymentIdentifier) -> ProviderPaymentDetail | None:
        by_virtual = (
            self._by_virtual_pos_order_id.get(identifier.virtual_pos_order_id)
            if identifier.virtual_pos_order_id
            else None
        )
        by_other = (
            self._by_other_trx_code.get(identifier.other_trx_code)
            if identifier.other_trx_code
            else None
        )
        if by_virtual is not None and by_other is not None and by_virtual != by_other:
            return None
        return by_virtual or by_other

    def save(self, payment: ProviderPaymentDetail) -> None:
        identifier = payment.identifier
        if identifier.virtual_pos_order_id:
            self._by_virtual_pos_order_id[identifier.virtual_pos_order_id] = payment
        if identifier.other_trx_code:
            self._by_other_trx_code[identifier.other_trx_code] = payment


class FakePaymentGateway:
    """Ağsız Moka-standard fake'i; ana ödeme akışına henüz bağlı değildir."""

    capabilities = MOKA_STANDARD_PROFILE

    def __init__(self, store: FakePaymentStore | None = None) -> None:
        self._store = store or InMemoryPaymentStore()

    def create_pool_payment(self, command: CreatePoolPaymentCommand) -> CreatePoolPaymentResult:
        existing = self._store.get(ProviderPaymentIdentifier(other_trx_code=command.other_trx_code))
        if existing is not None:
            return CreatePoolPaymentResult(
                outcome=ProviderOperationOutcome.SUCCESS,
                payment=existing,
            )

        identifier = ProviderPaymentIdentifier(
            virtual_pos_order_id=self._deterministic_virtual_pos_order_id(command.other_trx_code),
            other_trx_code=command.other_trx_code,
        )
        payment = ProviderPaymentDetail(
            identifier=identifier,
            amount_minor=command.amount_minor,
            currency=command.currency,
            status=ProviderPaymentStatus.POOL,
        )
        self._store.save(payment)
        return CreatePoolPaymentResult(outcome=ProviderOperationOutcome.SUCCESS, payment=payment)

    def approve_pool_payment(
        self, identifier: ProviderPaymentIdentifier
    ) -> ProviderOperationResult:
        payment = self._store.get(identifier)
        if payment is None:
            return self._failed(identifier, "PAYMENT_NOT_FOUND", "Provider ödemesi bulunamadı.")
        if not payment.is_pool_payment:
            return self._failed(identifier, "PAYMENT_NOT_POOL", "Ödeme pool türünde değil.")
        if payment.status == ProviderPaymentStatus.APPROVED:
            return self._failed(identifier, "PAYMENT_ALREADY_APPROVED", "Ödeme zaten approve edildi.")

        approved = replace(payment, status=ProviderPaymentStatus.APPROVED)
        self._store.save(approved)
        return ProviderOperationResult(
            outcome=ProviderOperationOutcome.SUCCESS,
            identifier=approved.identifier,
        )

    def undo_pool_approval(
        self, identifier: ProviderPaymentIdentifier
    ) -> ProviderOperationResult:
        payment = self._store.get(identifier)
        if payment is None:
            return self._failed(identifier, "PAYMENT_NOT_FOUND", "Provider ödemesi bulunamadı.")
        if not payment.is_pool_payment:
            return self._failed(identifier, "PAYMENT_NOT_POOL", "Ödeme pool türünde değil.")
        if payment.status != ProviderPaymentStatus.APPROVED:
            return self._failed(identifier, "PAYMENT_NOT_APPROVED", "Ödeme approve edilmedi.")

        restored = replace(payment, status=ProviderPaymentStatus.POOL)
        self._store.save(restored)
        return ProviderOperationResult(
            outcome=ProviderOperationOutcome.SUCCESS,
            identifier=restored.identifier,
        )

    def refund_payment(
        self, identifier: ProviderPaymentIdentifier
    ) -> ProviderOperationResult:
        payment = self._store.get(identifier)
        if payment is None:
            return self._failed(identifier, "PAYMENT_NOT_FOUND", "Provider ödemesi bulunamadı.")
        if not payment.is_pool_payment:
            return self._failed(identifier, "PAYMENT_NOT_POOL", "Ödeme pool türünde değil.")
        if payment.status is not ProviderPaymentStatus.APPROVED:
            return self._failed(identifier, "PAYMENT_NOT_APPROVED", "Ödeme approve edilmedi.")

        refunded = replace(payment, status=ProviderPaymentStatus.REFUNDED)
        self._store.save(refunded)
        return ProviderOperationResult(
            outcome=ProviderOperationOutcome.SUCCESS,
            identifier=refunded.identifier,
        )

    def get_payment_detail(self, query: PaymentDetailQuery) -> PaymentDetailResult:
        payment = self._store.get(query.identifier)
        if payment is None:
            return PaymentDetailResult(
                outcome=ProviderOperationOutcome.FAILED,
                provider_code="PAYMENT_NOT_FOUND",
                message="Provider ödemesi bulunamadı.",
            )
        return PaymentDetailResult(outcome=ProviderOperationOutcome.SUCCESS, payment=payment)

    @staticmethod
    def _deterministic_virtual_pos_order_id(other_trx_code: str) -> str:
        digest = sha256(other_trx_code.encode("utf-8")).hexdigest()[:20]
        return f"FAKE-VPOS-{digest}"

    @staticmethod
    def _failed(
        identifier: ProviderPaymentIdentifier,
        provider_code: str,
        message: str,
    ) -> ProviderOperationResult:
        return ProviderOperationResult(
            outcome=ProviderOperationOutcome.FAILED,
            identifier=identifier,
            provider_code=provider_code,
            message=message,
        )
