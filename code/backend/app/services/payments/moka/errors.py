"""Moka public error code kataloğu + domain error tipleri + eşleme tablosu (§2.5-2.6, §15).

Katalog yalnız plan dokümanının §2.5 (approve) ve §2.6 (undo) bölümlerinde
listelenen, dokümante edilmiş kodları içerir — mock ya da gerçek client
bunların dışında yeni bir Moka kodu icat etmez (§3.1, §15.3 "fail closed").

Bilinmeyen/dokümante edilmemiş bir `ResultCode` her zaman `ProviderContractViolation`'a
eşlenir: yayımlanmamış davranışa güvenerek release kararı verilmez.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Tüm Moka domain hatalarının temel sınıfı (§15.1)."""

    def __init__(self, *, result_code: str, result_message: str = "") -> None:
        self.result_code = result_code
        self.result_message = result_message
        super().__init__(f"{type(self).__name__}: {result_code} ({result_message})")


class ProviderAuthenticationError(ProviderError):
    """Kimlik/hesap/sanal pos yapılandırma hatası."""


class ProviderValidationError(ProviderError):
    """İstek biçimi veya işlem-durumu geçersiz (eksik/çelişkili alan, yanlış aşama)."""


class ProviderPaymentNotFound(ProviderError):
    """Belirtilen ödeme bayide bulunamadı."""


class ProviderPaymentAlreadyApproved(ProviderError):
    """Ödeme zaten onaylanmış — reconciliation gerektirir (§16.3)."""


class ProviderPaymentNotPool(ProviderError):
    """Ödeme bir havuz (pool) ödemesi değil."""


class ProviderOperationUnknown(ProviderError):
    """Sonuç belirsiz (beklenmeyen istisna / `EX`) — reconciliation ile çözülür."""


class ProviderTransportError(ProviderError):
    """HTTP/ağ seviyesinde başarısızlık — Moka ResultCode üretmedi (client katmanı fırlatır)."""


class ProviderBankDecline(ProviderError):
    """Banka seviyesinde ret (işlem katmanı, `Data.IsSuccessful == false`)."""


class ProviderContractViolation(ProviderError):
    """Dokümante edilmemiş/bilinmeyen ResultCode — fail-closed (§15.3)."""


# --- Public error code kataloğu (§2.5, §2.6) -----------------------------

AUTH_INVALID_REQUEST = "PaymentDealer.CheckPaymentDealerAuthentication.InvalidRequest"
AUTH_INVALID_ACCOUNT = "PaymentDealer.CheckPaymentDealerAuthentication.InvalidAccount"
AUTH_VIRTUAL_POS_NOT_FOUND = "PaymentDealer.CheckPaymentDealerAuthentication.VirtualPosNotFound"

APPROVE_IDENTIFIER_MUST_BE_GIVEN = (
    "PaymentDealer.DoApprovePoolPayment.OtherTrxCodeOrVirtualPosOrderIdMustGiven"
)
APPROVE_DEALER_PAYMENT_NOT_FOUND = "PaymentDealer.DoApprovePoolPayment.DealerPaymentNotFound"
APPROVE_PAYMENT_ALREADY_APPROVED = "PaymentDealer.DoApprovePoolPayment.PaymentAlreadyApproved"
APPROVE_PAYMENT_IS_NOT_POOL_PAYMENT = "PaymentDealer.DoApprovePoolPayment.PaymentIsNotPoolPayment"

UNDO_DEALER_PAYMENT_NOT_FOUND = "PaymentDealer.UndoApprovePoolPayment.DealerPaymentNotFound"
UNDO_IDENTIFIERS_NOT_MATCH = (
    "PaymentDealer.UndoApprovePoolPayment.OtherTrxCodeAndVirtualPosOrderIdNotMatch"
)
UNDO_IDENTIFIER_MUST_BE_GIVEN = (
    "PaymentDealer.UndoApprovePoolPayment.OtherTrxCodeOrVirtualPosOrderIdMustGiven"
)
UNDO_PAYMENT_NOT_APPROVED_YET = "PaymentDealer.UndoApprovePoolPayment.PaymentNotApprovedYet"
UNDO_PAYMENT_IS_NOT_POOL_PAYMENT = "PaymentDealer.UndoApprovePoolPayment.PaymentIsNotPoolPayment"
UNDO_PAYMENT_NOT_APPROVED_YET_FOR_SUB_DEALER = (
    "PaymentDealer.UndoApprovePoolPayment.PaymentNotApprovedYetForSubDealer"
)

UNEXPECTED_EXCEPTION = "EX"

#: Dokümante edilmiş tüm public kodların kümesi (katalog tamlığı testinde kullanılır).
KNOWN_RESULT_CODES: frozenset[str] = frozenset(
    {
        AUTH_INVALID_REQUEST,
        AUTH_INVALID_ACCOUNT,
        AUTH_VIRTUAL_POS_NOT_FOUND,
        APPROVE_IDENTIFIER_MUST_BE_GIVEN,
        APPROVE_DEALER_PAYMENT_NOT_FOUND,
        APPROVE_PAYMENT_ALREADY_APPROVED,
        APPROVE_PAYMENT_IS_NOT_POOL_PAYMENT,
        UNDO_DEALER_PAYMENT_NOT_FOUND,
        UNDO_IDENTIFIERS_NOT_MATCH,
        UNDO_IDENTIFIER_MUST_BE_GIVEN,
        UNDO_PAYMENT_NOT_APPROVED_YET,
        UNDO_PAYMENT_IS_NOT_POOL_PAYMENT,
        UNDO_PAYMENT_NOT_APPROVED_YET_FOR_SUB_DEALER,
        UNEXPECTED_EXCEPTION,
    }
)

# --- Eşleme tablosu (§15.2) ----------------------------------------------
#
# VirtualPosNotFound: hesap sanal pos için doğru yapılandırılmamış — kimlik
# bilgisi yanlış değil ama hesap bu işlemi yapamıyor; InvalidAccount ile aynı
# aile (ProviderAuthenticationError) olarak ele alınır.
#
# *IdentifierMustBeGiven / IdentifiersNotMatch / *NotApprovedYet(ForSubDealer):
# istek biçimi başlı başına yanlış değil ama işlemin mevcut durumuna göre
# geçersiz — ProviderValidationError (dokümanda ayrı bir "geçersiz durum" tipi
# tanımlanmadığı için en yakın karşılık).
RESULT_CODE_TO_DOMAIN_ERROR: dict[str, type[ProviderError]] = {
    AUTH_INVALID_REQUEST: ProviderValidationError,
    AUTH_INVALID_ACCOUNT: ProviderAuthenticationError,
    AUTH_VIRTUAL_POS_NOT_FOUND: ProviderAuthenticationError,
    APPROVE_IDENTIFIER_MUST_BE_GIVEN: ProviderValidationError,
    APPROVE_DEALER_PAYMENT_NOT_FOUND: ProviderPaymentNotFound,
    APPROVE_PAYMENT_ALREADY_APPROVED: ProviderPaymentAlreadyApproved,
    APPROVE_PAYMENT_IS_NOT_POOL_PAYMENT: ProviderPaymentNotPool,
    UNDO_DEALER_PAYMENT_NOT_FOUND: ProviderPaymentNotFound,
    UNDO_IDENTIFIERS_NOT_MATCH: ProviderValidationError,
    UNDO_IDENTIFIER_MUST_BE_GIVEN: ProviderValidationError,
    UNDO_PAYMENT_NOT_APPROVED_YET: ProviderValidationError,
    UNDO_PAYMENT_IS_NOT_POOL_PAYMENT: ProviderPaymentNotPool,
    UNDO_PAYMENT_NOT_APPROVED_YET_FOR_SUB_DEALER: ProviderValidationError,
    UNEXPECTED_EXCEPTION: ProviderOperationUnknown,
}


def map_result_code(result_code: str, *, result_message: str = "") -> ProviderError:
    """Envelope `ResultCode`'unu domain hatasına çevirir; bilinmeyen kod fail-closed döner (§15.3)."""

    error_type = RESULT_CODE_TO_DOMAIN_ERROR.get(result_code, ProviderContractViolation)
    return error_type(result_code=result_code, result_message=result_message)
