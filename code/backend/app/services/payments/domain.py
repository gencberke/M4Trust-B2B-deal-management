"""Ödeme gateway portunun provider'dan bağımsız domain tipleri.

Bu modül FastAPI, SQLite ve Moka'nın JSON alan adlarını bilmez. Provider'a
özgü DTO dönüşümü M1'de ``services.payments.moka`` altında yapılacaktır.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProviderOperationOutcome(str, Enum):
    """Bir provider isteğinin bilinen sonucu.

    ``unknown`` özellikle create/approve isteği gönderildikten sonraki transport
    timeout'ı için kullanılır; çağıran kör retry yerine reconcile etmelidir.
    """

    SUCCESS = "success"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ProviderPaymentStatus(str, Enum):
    """Gateway'nin ihtiyaç duyduğu en küçük provider ödeme durum kümesi."""

    POOL = "pool"
    APPROVED = "approved"
    REFUNDED = "refunded"


def _require_non_empty(value: str | None, *, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} boş olamaz.")


@dataclass(frozen=True)
class CreatePoolPaymentCommand:
    """Bir funding unit için bölünemez pool payment oluşturma komutu."""

    amount_minor: int
    currency: str
    other_trx_code: str
    description: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise ValueError("amount_minor tam sayı olmalıdır.")
        if self.amount_minor <= 0:
            raise ValueError("amount_minor sıfırdan büyük olmalıdır.")
        _require_non_empty(self.currency, field_name="currency")
        _require_non_empty(self.other_trx_code, field_name="other_trx_code")


@dataclass(frozen=True)
class ProviderPaymentIdentifier:
    """Ödemeyi provider id'si veya uygulamanın idempotency koduyla tanımlar."""

    virtual_pos_order_id: str | None = None
    other_trx_code: str | None = None

    def __post_init__(self) -> None:
        if not self.virtual_pos_order_id and not self.other_trx_code:
            raise ValueError("En az bir provider ödeme tanımlayıcısı gereklidir.")
        if self.virtual_pos_order_id is not None:
            _require_non_empty(self.virtual_pos_order_id, field_name="virtual_pos_order_id")
        if self.other_trx_code is not None:
            _require_non_empty(self.other_trx_code, field_name="other_trx_code")


@dataclass(frozen=True)
class PaymentDetailQuery:
    """Detay/reconciliation sorgusunun domain biçimi."""

    identifier: ProviderPaymentIdentifier


@dataclass(frozen=True)
class ProviderPaymentDetail:
    """Provider'dan dönen veya fake store'da tutulan normalize ödeme görünümü.

    Moka detail contract'ı yalnız kimlik ve durum döndürdüğü için tutar/para
    birimi reconciliation sonucunda bilinmeyebilir; create sonucu ve fake
    store kayıtlarında bu alanlar doludur.
    """

    identifier: ProviderPaymentIdentifier
    amount_minor: int | None
    currency: str | None
    status: ProviderPaymentStatus
    is_pool_payment: bool = True

    def __post_init__(self) -> None:
        if self.amount_minor is not None:
            if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
                raise ValueError("amount_minor tam sayı olmalıdır.")
            if self.amount_minor <= 0:
                raise ValueError("amount_minor sıfırdan büyük olmalıdır.")
        if self.currency is not None:
            _require_non_empty(self.currency, field_name="currency")


@dataclass(frozen=True)
class ProviderOperationResult:
    """Approve/undo gibi para hareketi operasyonlarının normalize sonucu."""

    outcome: ProviderOperationOutcome
    identifier: ProviderPaymentIdentifier | None = None
    provider_code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class CreatePoolPaymentResult:
    """Pool payment oluşturma sonucunu ve oluşan ödeme bilgisini taşır."""

    outcome: ProviderOperationOutcome
    payment: ProviderPaymentDetail | None = None
    provider_code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class PaymentDetailResult:
    """Provider ödeme-detay sorgusunun normalize sonucu."""

    outcome: ProviderOperationOutcome
    payment: ProviderPaymentDetail | None = None
    provider_code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class ProviderCapabilities:
    """Funding-plan derleyicisinin kullanacağı provider yetenek profili."""

    supports_pool_payment: bool
    supports_partial_pool_approval: bool
    supports_multiple_approvals_per_payment: bool
    supports_approval_undo: bool
    supports_fixed_tranches: bool
    supports_marketplace_subdealers: bool


MOKA_STANDARD_PROFILE = ProviderCapabilities(
    supports_pool_payment=True,
    supports_partial_pool_approval=False,
    supports_multiple_approvals_per_payment=False,
    supports_approval_undo=True,
    supports_fixed_tranches=True,
    supports_marketplace_subdealers=False,
)
