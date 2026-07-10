"""Mock'a özel giriş (wire) şemaları + `GetPaymentList` best-effort şeması.

`contracts.py`'deki `IdentifierFields`/`DetailQueryFields` client tarafı için
doğrudur (en az bir identifier zorunlu, pydantic validator ile). Ancak mock
sunucu bu validator'ı FastAPI gövde ayrıştırmasında kullanırsa, eksik identifier
durumunda framework otomatik 422 döner — oysa Moka contract'ı bu durumda
documented `OtherTrxCodeOrVirtualPosOrderIdMustGiven` gibi bir ApiResponse
zarfı bekler (§14.2). Bu yüzden mock, giriş kapısında validator'sız "ham" alan
tiplerini kullanır; "en az biri zorunlu" kontrolünü `app.py` elle yapıp doğru
public error code'u döner.

`GetPaymentList` yalnız §14.1'de isim olarak geçer; plan §2.x'te alan
seviyesinde tanımlanmadı ve `PaymentGateway` port'unda (Berke, §6) hiç yoktur
— bu yüzden frozen `contracts.py`'ye eklenmez, best-effort şema burada tutulur.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backend.app.services.payments.moka.contracts import (
    MokaContractModel,
    PaymentDealerAuthentication,
    PaymentTrxDetail,
)


class RawIdentifierFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    VirtualPosOrderId: str | None = None
    OtherTrxCode: str | None = None


class RawDetailQueryFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    PaymentId: str | None = None
    OtherTrxCode: str | None = None


class DoApprovePoolPaymentWireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    PaymentDealerAuthentication: PaymentDealerAuthentication
    PaymentDealerRequest: RawIdentifierFields


class UndoApprovePoolPaymentWireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    PaymentDealerAuthentication: PaymentDealerAuthentication
    PaymentDealerRequest: RawIdentifierFields


class GetDealerPaymentTrxDetailListWireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    PaymentDealerAuthentication: PaymentDealerAuthentication
    PaymentDealerRequest: RawDetailQueryFields


class GetPaymentListWireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    PaymentDealerAuthentication: PaymentDealerAuthentication


class GetPaymentListData(MokaContractModel):
    TrxDetailList: list[PaymentTrxDetail]


class GetPaymentListResponse(MokaContractModel):
    Data: GetPaymentListData | None
    ResultCode: str
    ResultMessage: str
    Exception: str | None = None
