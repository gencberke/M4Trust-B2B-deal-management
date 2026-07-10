"""Moka PaymentDealer public contract'ıyla gerçek HTTP konuşan sync client."""

from __future__ import annotations

from copy import deepcopy
from typing import Callable, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from backend.app.config import Settings
from backend.app.services.payments.domain import (
    CreatePoolPaymentCommand,
    CreatePoolPaymentResult,
    MOKA_STANDARD_PROFILE,
    PaymentDetailQuery,
    PaymentDetailResult,
    ProviderOperationOutcome,
    ProviderOperationResult,
    ProviderPaymentIdentifier,
)
from backend.app.services.payments.moka.authentication import generate_check_key
from backend.app.services.payments.moka.contracts import (
    DetailQueryFields,
    DirectPaymentFields,
    DoApprovePoolPaymentRequest,
    DoApprovePoolPaymentResponse,
    DoDirectPaymentRequest,
    DoDirectPaymentResponse,
    GetDealerPaymentTrxDetailListRequest,
    GetDealerPaymentTrxDetailListResponse,
    IdentifierFields,
    PaymentDealerAuthentication,
    UndoApprovePoolPaymentRequest,
    UndoApprovePoolPaymentResponse,
)
from backend.app.services.payments.moka.errors import (
    ProviderContractViolation,
    ProviderTransportError,
    ProviderValidationError,
)
from backend.app.services.payments.moka.mapper import (
    map_create_response,
    map_detail_response,
    map_operation_response,
)
from backend.app.services.payments.moka.redaction import build_redacted_trace
from backend.app.services.payments.moka.serialization import (
    dumps_json,
    loads_json,
    minor_units_to_decimal,
    to_moka_currency,
)

_ResponseT = TypeVar("_ResponseT", bound=BaseModel)
TraceSink = Callable[[dict], None]

MOKA_CONTRACT_PROFILE = "moka_payment_dealer_pool_v1"

_DIRECT_PAYMENT_PATH = "/PaymentDealer/DoDirectPayment"
_APPROVE_PATH = "/PaymentDealer/DoApprovePoolPayment"
_UNDO_PATH = "/PaymentDealer/UndoApprovePoolPayment"
_DETAIL_PATH = "/PaymentDealer/GetDealerPaymentTrxDetailList"


class _RequestTimedOut(Exception):
    """Internal sentinel; public API timeout'ı typed unknown result'a çevirir."""


class MokaPaymentDealerClient:
    """Moka standard pool-payment profilinin sync HTTP adapter'ı.

    Client additive yan paneldir; mevcut ``make_payment_provider`` factory'sine
    M1'de bağlanmaz. Create/approve için otomatik retry uygulanmaz.
    """

    capabilities = MOKA_STANDARD_PROFILE

    def __init__(
        self,
        *,
        base_url: str,
        dealer_code: str,
        username: str,
        password: str,
        card_token: str,
        software: str = "M4Trust",
        timeout_seconds: float = 20.0,
        http_client: httpx.Client | None = None,
        trace_sink: TraceSink | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._dealer_code = dealer_code
        self._username = username
        self._password = password
        self._card_token = card_token
        self._software = software
        self._timeout = httpx.Timeout(
            connect=5.0,
            read=timeout_seconds,
            write=timeout_seconds,
            pool=5.0,
        )
        self._http_client = http_client or httpx.Client()
        self._owns_http_client = http_client is None
        self._trace_sink = trace_sink
        self._last_trace: dict | None = None

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        http_client: httpx.Client | None = None,
        trace_sink: TraceSink | None = None,
    ) -> "MokaPaymentDealerClient":
        if settings.moka_contract_profile != MOKA_CONTRACT_PROFILE:
            raise ProviderValidationError(
                result_code="PROVIDER_UNSUPPORTED_CONTRACT_PROFILE",
                result_message=f"Desteklenmeyen Moka profili: {settings.moka_contract_profile}",
            )
        return cls(
            base_url=settings.moka_base_url,
            dealer_code=settings.moka_dealer_code,
            username=settings.moka_username,
            password=settings.moka_password,
            card_token=settings.moka_card_token,
            software=settings.moka_software,
            timeout_seconds=settings.moka_timeout_seconds,
            http_client=http_client,
            trace_sink=trace_sink,
        )

    @property
    def last_trace(self) -> dict | None:
        """Yalnız redacted trace'in savunmacı kopyasını döndürür."""

        return deepcopy(self._last_trace)

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def __enter__(self) -> "MokaPaymentDealerClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def create_pool_payment(self, command: CreatePoolPaymentCommand) -> CreatePoolPaymentResult:
        request = DoDirectPaymentRequest(
            PaymentDealerAuthentication=self._authentication(),
            PaymentDealerRequest=DirectPaymentFields(
                CardHolderFullName="M4Trust Demo",
                CardToken=self._card_token,
                Amount=minor_units_to_decimal(command.amount_minor),
                Currency=to_moka_currency(command.currency),
                InstallmentNumber=1,
                ClientIP="127.0.0.1",
                OtherTrxCode=command.other_trx_code,
                IsPoolPayment=1,
                IsTokenized=0,
                Software=self._software,
                Description=command.description or "",
                IsPreAuth=0,
                BuyerInformation=None,
            ),
        )
        try:
            response = self._post(_DIRECT_PAYMENT_PATH, request, DoDirectPaymentResponse)
        except _RequestTimedOut:
            return CreatePoolPaymentResult(
                outcome=ProviderOperationOutcome.UNKNOWN,
                provider_code="TRANSPORT_TIMEOUT",
                message="Create sonucu belirsiz; OtherTrxCode ile reconciliation gerekir.",
            )
        return map_create_response(response, command)

    def approve_pool_payment(
        self, identifier: ProviderPaymentIdentifier
    ) -> ProviderOperationResult:
        request = DoApprovePoolPaymentRequest(
            PaymentDealerAuthentication=self._authentication(),
            PaymentDealerRequest=self._identifier_fields(identifier),
        )
        try:
            response = self._post(_APPROVE_PATH, request, DoApprovePoolPaymentResponse)
        except _RequestTimedOut:
            return self._unknown_operation(identifier, operation="Approve")
        return map_operation_response(response, identifier)

    def undo_pool_approval(
        self, identifier: ProviderPaymentIdentifier
    ) -> ProviderOperationResult:
        request = UndoApprovePoolPaymentRequest(
            PaymentDealerAuthentication=self._authentication(),
            PaymentDealerRequest=self._identifier_fields(identifier),
        )
        try:
            response = self._post(_UNDO_PATH, request, UndoApprovePoolPaymentResponse)
        except _RequestTimedOut:
            return self._unknown_operation(identifier, operation="Undo")
        return map_operation_response(response, identifier)

    def get_payment_detail(self, query: PaymentDetailQuery) -> PaymentDetailResult:
        identifier = query.identifier
        request = GetDealerPaymentTrxDetailListRequest(
            PaymentDealerAuthentication=self._authentication(),
            PaymentDealerRequest=DetailQueryFields(
                PaymentId=identifier.virtual_pos_order_id,
                OtherTrxCode=identifier.other_trx_code,
            ),
        )
        try:
            response = self._post(
                _DETAIL_PATH,
                request,
                GetDealerPaymentTrxDetailListResponse,
            )
        except _RequestTimedOut:
            return PaymentDetailResult(
                outcome=ProviderOperationOutcome.UNKNOWN,
                provider_code="TRANSPORT_TIMEOUT",
                message="Detail sorgusu zaman aşımına uğradı.",
            )
        return map_detail_response(response, query)

    def _authentication(self) -> PaymentDealerAuthentication:
        return PaymentDealerAuthentication(
            DealerCode=self._dealer_code,
            Username=self._username,
            Password=self._password,
            CheckKey=generate_check_key(
                dealer_code=self._dealer_code,
                username=self._username,
                password=self._password,
            ),
        )

    @staticmethod
    def _identifier_fields(identifier: ProviderPaymentIdentifier) -> IdentifierFields:
        return IdentifierFields(
            VirtualPosOrderId=identifier.virtual_pos_order_id,
            OtherTrxCode=identifier.other_trx_code,
        )

    def _post(
        self,
        endpoint: str,
        request: BaseModel,
        response_model: type[_ResponseT],
    ) -> _ResponseT:
        request_payload = request.model_dump(mode="python")
        content = dumps_json(request_payload)
        try:
            response = self._http_client.post(
                f"{self._base_url}{endpoint}",
                content=content.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            self._record_trace(
                endpoint=endpoint,
                request=request_payload,
                response={"transport_error": "timeout"},
            )
            raise _RequestTimedOut from exc
        except httpx.TransportError as exc:
            self._record_trace(
                endpoint=endpoint,
                request=request_payload,
                response={"transport_error": type(exc).__name__},
            )
            raise ProviderTransportError(
                result_code="TRANSPORT_ERROR",
                result_message=type(exc).__name__,
            ) from exc

        try:
            response_payload = loads_json(response.content)
        except (ValueError, TypeError) as exc:
            self._record_trace(
                endpoint=endpoint,
                request=request_payload,
                response={"http_status": response.status_code, "invalid_json": True},
            )
            raise ProviderContractViolation(
                result_code="INVALID_PROVIDER_JSON",
                result_message="Moka cevabı geçerli JSON değil.",
            ) from exc

        self._record_trace(
            endpoint=endpoint,
            request=request_payload,
            response=response_payload,
        )
        if not 200 <= response.status_code < 300:
            raise ProviderTransportError(
                result_code=f"HTTP_{response.status_code}",
                result_message="Moka HTTP isteği başarısız oldu.",
            )
        try:
            return response_model.model_validate(response_payload)
        except ValidationError as exc:
            raise ProviderContractViolation(
                result_code="INVALID_PROVIDER_RESPONSE",
                result_message="Moka cevabı frozen contract DTO'suna uymuyor.",
            ) from exc

    def _record_trace(self, *, endpoint: str, request: dict, response: object) -> None:
        check_key = request["PaymentDealerAuthentication"]["CheckKey"]
        trace = build_redacted_trace(
            endpoint=endpoint,
            request=request,
            response=response,
            sensitive_values=(self._password, self._card_token, check_key),
        )
        self._last_trace = trace
        if self._trace_sink is not None:
            self._trace_sink(deepcopy(trace))

    @staticmethod
    def _unknown_operation(
        identifier: ProviderPaymentIdentifier,
        *,
        operation: str,
    ) -> ProviderOperationResult:
        return ProviderOperationResult(
            outcome=ProviderOperationOutcome.UNKNOWN,
            identifier=identifier,
            provider_code="TRANSPORT_TIMEOUT",
            message=f"{operation} sonucu belirsiz; reconciliation gerekir.",
        )
