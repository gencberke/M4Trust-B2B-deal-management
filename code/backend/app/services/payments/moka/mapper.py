"""Frozen Moka DTO'larını provider-bağımsız ödeme domain sonuçlarına map eder."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.services.payments.domain import (
    CreatePoolPaymentCommand,
    CreatePoolPaymentResult,
    PaymentDetailQuery,
    PaymentDetailResult,
    ProviderOperationOutcome,
    ProviderOperationResult,
    ProviderPaymentDetail,
    ProviderPaymentIdentifier,
    ProviderPaymentStatus,
)
from backend.app.services.payments.moka.contracts import (
    ApiResponse,
    DoApprovePoolPaymentResponse,
    DoDirectPaymentResponse,
    GetDealerPaymentTrxDetailListResponse,
    PaymentTrxDetail,
    UndoApprovePoolPaymentResponse,
)
from backend.app.services.payments.moka.errors import (
    ProviderBankDecline,
    ProviderContractViolation,
    ProviderOperationUnknown,
    map_result_code,
)


@dataclass(frozen=True)
class _MappedFailure:
    outcome: ProviderOperationOutcome
    code: str
    message: str


def _contract_violation(message: str) -> ProviderContractViolation:
    return ProviderContractViolation(
        result_code="PROVIDER_CONTRACT_VIOLATION",
        result_message=message,
    )


def _map_envelope_failure(response: ApiResponse) -> _MappedFailure | None:
    if response.ResultCode == "Success":
        return None
    if response.Data is not None:
        raise _contract_violation("Başarısız provider zarfında Data null olmalıdır.")

    error = map_result_code(response.ResultCode, result_message=response.ResultMessage)
    if isinstance(error, ProviderContractViolation):
        raise error
    outcome = (
        ProviderOperationOutcome.UNKNOWN
        if isinstance(error, ProviderOperationUnknown)
        else ProviderOperationOutcome.FAILED
    )
    return _MappedFailure(outcome, error.result_code, error.result_message)


def _map_bank_failure(*, result_code: str, result_message: str) -> _MappedFailure:
    error = ProviderBankDecline(
        result_code=result_code or "PROVIDER_BANK_DECLINE",
        result_message=result_message,
    )
    return _MappedFailure(
        ProviderOperationOutcome.FAILED,
        error.result_code,
        error.result_message,
    )


def map_create_response(
    response: DoDirectPaymentResponse,
    command: CreatePoolPaymentCommand,
) -> CreatePoolPaymentResult:
    failure = _map_envelope_failure(response)
    if failure is not None:
        return CreatePoolPaymentResult(
            outcome=failure.outcome,
            provider_code=failure.code,
            message=failure.message,
        )

    data = response.Data
    if data is None:
        raise _contract_violation("Başarılı create zarfında Data zorunludur.")
    if not data.IsSuccessful:
        failure = _map_bank_failure(
            result_code=data.ResultCode,
            result_message=data.ResultMessage,
        )
        return CreatePoolPaymentResult(
            outcome=failure.outcome,
            provider_code=failure.code,
            message=failure.message,
        )
    if not data.VirtualPosOrderId:
        raise _contract_violation("Başarılı create cevabında VirtualPosOrderId boş olamaz.")

    payment = ProviderPaymentDetail(
        identifier=ProviderPaymentIdentifier(
            virtual_pos_order_id=data.VirtualPosOrderId,
            other_trx_code=command.other_trx_code,
        ),
        amount_minor=command.amount_minor,
        currency=command.currency,
        status=ProviderPaymentStatus.POOL,
    )
    return CreatePoolPaymentResult(
        outcome=ProviderOperationOutcome.SUCCESS,
        payment=payment,
    )


def map_operation_response(
    response: DoApprovePoolPaymentResponse | UndoApprovePoolPaymentResponse,
    identifier: ProviderPaymentIdentifier,
) -> ProviderOperationResult:
    failure = _map_envelope_failure(response)
    if failure is not None:
        return ProviderOperationResult(
            outcome=failure.outcome,
            identifier=identifier,
            provider_code=failure.code,
            message=failure.message,
        )

    data = response.Data
    if data is None:
        raise _contract_violation("Başarılı approve/undo zarfında Data zorunludur.")
    if not data.IsSuccessful:
        failure = _map_bank_failure(
            result_code=data.ResultCode,
            result_message=data.ResultMessage,
        )
        return ProviderOperationResult(
            outcome=failure.outcome,
            identifier=identifier,
            provider_code=failure.code,
            message=failure.message,
        )
    if not data.VirtualPosOrderId:
        raise _contract_violation("Başarılı approve/undo cevabında VirtualPosOrderId boş olamaz.")
    if (
        identifier.virtual_pos_order_id
        and identifier.virtual_pos_order_id != data.VirtualPosOrderId
    ):
        raise _contract_violation("Provider cevabı istenen VirtualPosOrderId ile eşleşmiyor.")

    resolved_identifier = ProviderPaymentIdentifier(
        virtual_pos_order_id=data.VirtualPosOrderId,
        other_trx_code=identifier.other_trx_code,
    )
    return ProviderOperationResult(
        outcome=ProviderOperationOutcome.SUCCESS,
        identifier=resolved_identifier,
    )


def _matches_query(detail: PaymentTrxDetail, query: PaymentDetailQuery) -> bool:
    identifier = query.identifier
    if identifier.virtual_pos_order_id and detail.VirtualPosOrderId != identifier.virtual_pos_order_id:
        return False
    if identifier.other_trx_code and detail.OtherTrxCode != identifier.other_trx_code:
        return False
    return True


def _map_payment_status(detail: PaymentTrxDetail) -> ProviderPaymentStatus:
    status_pair = (detail.PaymentStatus, detail.TrxStatus)
    if status_pair == (0, 0):
        return ProviderPaymentStatus.POOL
    if status_pair == (2, 1):
        return ProviderPaymentStatus.APPROVED
    raise _contract_violation(
        f"Dokümante edilmemiş Moka ödeme durumu: {status_pair[0]}/{status_pair[1]}"
    )


def map_detail_response(
    response: GetDealerPaymentTrxDetailListResponse,
    query: PaymentDetailQuery,
) -> PaymentDetailResult:
    failure = _map_envelope_failure(response)
    if failure is not None:
        return PaymentDetailResult(
            outcome=failure.outcome,
            provider_code=failure.code,
            message=failure.message,
        )

    data = response.Data
    if data is None:
        raise _contract_violation("Başarılı detail zarfında Data zorunludur.")
    matching = [detail for detail in data.TrxDetailList if _matches_query(detail, query)]
    if not matching:
        return PaymentDetailResult(
            outcome=ProviderOperationOutcome.FAILED,
            provider_code="PROVIDER_PAYMENT_NOT_FOUND",
            message="Provider ödemesi bulunamadı.",
        )
    if len(matching) != 1:
        raise _contract_violation("Detail sorgusu birden fazla ödeme döndürdü.")

    detail = matching[0]
    payment = ProviderPaymentDetail(
        identifier=ProviderPaymentIdentifier(
            virtual_pos_order_id=detail.VirtualPosOrderId,
            other_trx_code=detail.OtherTrxCode,
        ),
        amount_minor=None,
        currency=None,
        status=_map_payment_status(detail),
    )
    return PaymentDetailResult(
        outcome=ProviderOperationOutcome.SUCCESS,
        payment=payment,
    )
