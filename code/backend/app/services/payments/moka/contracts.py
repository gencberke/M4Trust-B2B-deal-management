"""Moka PaymentDealer public contract DTO'ları (profil: moka_payment_dealer_pool_v1).

Alan adları ve casing, plan dokümanının §2 (public contract) ve §22.1 (exact
casing testi) bölümleriyle birebir eşleşir
(plans/planning/m4trust_moka_contract_faithful_payment_refactor_plan.md).
Bu modül `feat/moka-contract-models` merge sonrası donar (freeze) — yeni
alan/hata kodu ayrı bir ortak contract PR'ı gerektirir (§5.1, plans/ready/01).

Her istek gövdesi Moka'nın tekil "PaymentDealerRequest" zarf anahtarını korur;
bu isim tüm endpoint'lerde aynı JSON anahtarıdır, yalnızca içerik şekli
endpoint'e göre değişir — bu yüzden Python tarafında her endpoint için ayrı
bir sınıf tanımlanır (DoDirectPaymentRequest, DoApprovePoolPaymentRequest, ...)
ama hepsi aynı "PaymentDealerRequest" JSON alanı altında taşınır.

Mock server (M1-YUSUF) bu modelleri import eder; M4Trust domain kodu bu
DTO'ları asla doğrudan kullanmaz — dönüşüm Berke'nin `mapper.py`'sinde olur
(§5.1 "aynı DTO contract, farklı provider/server davranışı").
"""

from __future__ import annotations

from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator

_DataT = TypeVar("_DataT", bound=BaseModel)


class MokaContractModel(BaseModel):
    """Tüm Moka contract DTO'larının ortak temeli.

    `extra="forbid"`: dokümante edilmemiş alan sızıntısını (ne eksik ne
    fazla) erken yakalar — §22.1 "extra/missing field policy dondurulur".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Ortak zarf (§2.2) -------------------------------------------------


class ApiResponse(MokaContractModel, Generic[_DataT]):
    """Ortak ApiResponse zarfı — başarı/başarısızlıkta hep aynı şekli korur (§2.2)."""

    Data: _DataT | None
    ResultCode: str
    ResultMessage: str
    Exception: str | None = None


# --- Authentication (§2.3) ---------------------------------------------


class PaymentDealerAuthentication(MokaContractModel):
    DealerCode: str
    Username: str
    Password: str
    CheckKey: str


# --- DoDirectPayment (§2.4) ---------------------------------------------


class DirectPaymentFields(MokaContractModel):
    """DoDirectPayment `PaymentDealerRequest` alan seti (standard pool profili, §2.4)."""

    CardHolderFullName: str
    CardToken: str
    Amount: Decimal
    Currency: str
    InstallmentNumber: int
    ClientIP: str
    OtherTrxCode: str
    IsPoolPayment: int = 1
    IsTokenized: int = 0
    Software: str
    Description: str = ""
    IsPreAuth: int = 0
    BuyerInformation: str | None = None


class DoDirectPaymentRequest(MokaContractModel):
    PaymentDealerAuthentication: PaymentDealerAuthentication
    PaymentDealerRequest: DirectPaymentFields


class DoDirectPaymentData(MokaContractModel):
    IsSuccessful: bool
    ResultCode: str
    ResultMessage: str
    VirtualPosOrderId: str


class DoDirectPaymentResponse(ApiResponse[DoDirectPaymentData]):
    pass


# --- Approve / Undo (§2.5, §2.6) ----------------------------------------


class IdentifierFields(MokaContractModel):
    """Approve/undo `PaymentDealerRequest` — VirtualPosOrderId veya OtherTrxCode zorunlu (§2.5-2.6)."""

    VirtualPosOrderId: str | None = None
    OtherTrxCode: str | None = None

    @model_validator(mode="after")
    def _require_one_identifier(self) -> "IdentifierFields":
        if not self.VirtualPosOrderId and not self.OtherTrxCode:
            raise ValueError("VirtualPosOrderId veya OtherTrxCode zorunludur.")
        return self


class DoApprovePoolPaymentRequest(MokaContractModel):
    PaymentDealerAuthentication: PaymentDealerAuthentication
    PaymentDealerRequest: IdentifierFields


class UndoApprovePoolPaymentRequest(MokaContractModel):
    PaymentDealerAuthentication: PaymentDealerAuthentication
    PaymentDealerRequest: IdentifierFields


class ApproveOrUndoData(MokaContractModel):
    IsSuccessful: bool
    ResultCode: str
    ResultMessage: str
    VirtualPosOrderId: str


class DoApprovePoolPaymentResponse(ApiResponse[ApproveOrUndoData]):
    pass


class UndoApprovePoolPaymentResponse(ApiResponse[ApproveOrUndoData]):
    pass


# --- Detail query (§2.7) -------------------------------------------------


class DetailQueryFields(MokaContractModel):
    """`GetDealerPaymentTrxDetailList` `PaymentDealerRequest` — PaymentId veya OtherTrxCode zorunlu."""

    PaymentId: str | None = None
    OtherTrxCode: str | None = None

    @model_validator(mode="after")
    def _require_one_identifier(self) -> "DetailQueryFields":
        if not self.PaymentId and not self.OtherTrxCode:
            raise ValueError("PaymentId veya OtherTrxCode zorunludur.")
        return self


class GetDealerPaymentTrxDetailListRequest(MokaContractModel):
    PaymentDealerAuthentication: PaymentDealerAuthentication
    PaymentDealerRequest: DetailQueryFields


class PaymentTrxDetail(MokaContractModel):
    """Reconciliation minimumu (§2.7) — internal statü burada türetilmez, yalnız taşınır."""

    OtherTrxCode: str
    VirtualPosOrderId: str
    PaymentStatus: int
    TrxStatus: int


class GetDealerPaymentTrxDetailListData(MokaContractModel):
    TrxDetailList: list[PaymentTrxDetail]


class GetDealerPaymentTrxDetailListResponse(ApiResponse[GetDealerPaymentTrxDetailListData]):
    pass
