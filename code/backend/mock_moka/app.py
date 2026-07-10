"""Bağımsız contract-faithful Moka mock servisi — FastAPI app (GATE M1-YUSUF).

Ana backend'e import/register EDİLMEZ; kendi process'inde çalışır:

    uvicorn backend.mock_moka.app:app --port 8001

Endpoint'ler (§14.1): DoDirectPayment, DoApprovePoolPayment,
UndoApprovePoolPayment, GetDealerPaymentTrxDetailList, GetPaymentList.
Public error code'ları yalnız `payments/moka/errors.py` kataloğundan kullanır
(§3.1 "mock'a dokümante edilmemiş davranış eklenmez").

Ayarlar (`MockMokaSettings.from_env()`) ve DB bağlantısı her istekte taze
okunur/açılır — ana backend'in `routers/transactions.py` deseniyle aynı;
bu sayede testler `MOCK_MOKA_DB_PATH`/`MOCK_MOKA_*` env override'larıyla
izole çalışabilir.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException, Request

from backend.app.services.payments.moka.contracts import (
    ApproveOrUndoData,
    DoApprovePoolPaymentResponse,
    DoDirectPaymentData,
    DoDirectPaymentRequest,
    DoDirectPaymentResponse,
    GetDealerPaymentTrxDetailListData,
    GetDealerPaymentTrxDetailListResponse,
    PaymentTrxDetail,
    UndoApprovePoolPaymentResponse,
)
from backend.app.services.payments.moka.errors import (
    APPROVE_DEALER_PAYMENT_NOT_FOUND,
    APPROVE_IDENTIFIER_MUST_BE_GIVEN,
    APPROVE_PAYMENT_ALREADY_APPROVED,
    APPROVE_PAYMENT_IS_NOT_POOL_PAYMENT,
    AUTH_INVALID_REQUEST,
    UNDO_DEALER_PAYMENT_NOT_FOUND,
    UNDO_IDENTIFIER_MUST_BE_GIVEN,
    UNDO_IDENTIFIERS_NOT_MATCH,
    UNDO_PAYMENT_IS_NOT_POOL_PAYMENT,
    UNDO_PAYMENT_NOT_APPROVED_YET,
)

from . import db, status_mapper
from .auth import authenticate
from .config import MockMokaSettings
from .schemas import (
    DoApprovePoolPaymentWireRequest,
    GetDealerPaymentTrxDetailListWireRequest,
    GetPaymentListData,
    GetPaymentListResponse,
    GetPaymentListWireRequest,
    UndoApprovePoolPaymentWireRequest,
)

_DEMO_TOKEN_BANK_DECLINE = "DEMO-TOKEN-BANK-DECLINE"
_DEMO_TOKEN_TIMEOUT_AFTER_CREATE = "DEMO-TOKEN-TIMEOUT-AFTER-CREATE"

_router = APIRouter()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Password/CheckKey/CardToken hiçbir zaman `mock_operations`'a açık yazılmaz."""

    redacted = json.loads(json.dumps(payload, default=str))
    auth = redacted.get("PaymentDealerAuthentication")
    if isinstance(auth, dict):
        if auth.get("Password") is not None:
            auth["Password"] = "***"
        if auth.get("CheckKey") is not None:
            auth["CheckKey"] = "***"
    inner = redacted.get("PaymentDealerRequest")
    if isinstance(inner, dict) and inner.get("CardToken"):
        token = str(inner["CardToken"])
        inner["CardToken"] = f"token_****{token[-4:]}" if len(token) > 4 else "token_****"
    return redacted


def _record_operation(
    conn: sqlite3.Connection,
    endpoint: str,
    other_trx_code: str | None,
    request_payload: dict,
    response_payload: dict,
) -> None:
    conn.execute(
        """
        INSERT INTO mock_operations
            (endpoint, other_trx_code, redacted_request, redacted_response, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            endpoint,
            other_trx_code,
            json.dumps(_redact(request_payload), ensure_ascii=False),
            json.dumps(_redact(response_payload), ensure_ascii=False),
            _utc_now_iso(),
        ),
    )
    conn.commit()


def _find_by_other_trx_code(conn: sqlite3.Connection, other_trx_code: str | None):
    if not other_trx_code:
        return None
    return conn.execute(
        "SELECT * FROM dealer_payments WHERE other_trx_code = ?", (other_trx_code,)
    ).fetchone()


def _find_by_vpos_id(conn: sqlite3.Connection, virtual_pos_order_id: str | None):
    if not virtual_pos_order_id:
        return None
    return conn.execute(
        "SELECT * FROM dealer_payments WHERE virtual_pos_order_id = ?", (virtual_pos_order_id,)
    ).fetchone()


# --- DoDirectPayment (§2.4) ----------------------------------------------


@_router.post("/PaymentDealer/DoDirectPayment", response_model=DoDirectPaymentResponse)
def do_direct_payment(body: DoDirectPaymentRequest) -> DoDirectPaymentResponse:
    settings = MockMokaSettings.from_env()
    conn = db.connect(settings.db_path)
    try:
        request_payload = body.model_dump(mode="json")
        fields = body.PaymentDealerRequest

        error_code = authenticate(body.PaymentDealerAuthentication, settings)
        if error_code:
            response = DoDirectPaymentResponse(
                Data=None, ResultCode=error_code, ResultMessage="", Exception=None
            )
            _record_operation(
                conn, "DoDirectPayment", fields.OtherTrxCode, request_payload,
                response.model_dump(mode="json"),
            )
            return response

        existing = _find_by_other_trx_code(conn, fields.OtherTrxCode)
        if existing is not None:
            # İdempotent: aynı OtherTrxCode için ikinci kayıt açılmaz (§16.1).
            response = DoDirectPaymentResponse(
                Data=DoDirectPaymentData(
                    IsSuccessful=True,
                    ResultCode="",
                    ResultMessage="",
                    VirtualPosOrderId=existing["virtual_pos_order_id"],
                ),
                ResultCode="Success",
                ResultMessage="",
                Exception=None,
            )
            _record_operation(
                conn, "DoDirectPayment", fields.OtherTrxCode, request_payload,
                response.model_dump(mode="json"),
            )
            return response

        if fields.CardToken == _DEMO_TOKEN_BANK_DECLINE:
            # Banka/işlem katmanı reddi — envelope Success kalır, Data.IsSuccessful=false (§2.2).
            response = DoDirectPaymentResponse(
                Data=DoDirectPaymentData(
                    IsSuccessful=False,
                    ResultCode="BankDeclined",
                    ResultMessage="Banka tarafindan reddedildi (demo).",
                    VirtualPosOrderId="",
                ),
                ResultCode="Success",
                ResultMessage="",
                Exception=None,
            )
            _record_operation(
                conn, "DoDirectPayment", fields.OtherTrxCode, request_payload,
                response.model_dump(mode="json"),
            )
            return response

        virtual_pos_order_id = f"ORDER-DEMO-{uuid4()}"
        conn.execute(
            """
            INSERT INTO dealer_payments
                (other_trx_code, virtual_pos_order_id, amount, currency, is_pool_payment,
                 payment_status, trx_status, statement_closed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                fields.OtherTrxCode,
                virtual_pos_order_id,
                str(fields.Amount),
                fields.Currency,
                1 if fields.IsPoolPayment else 0,
                status_mapper.PAYMENT_STATUS_PENDING,
                status_mapper.TRX_STATUS_PENDING,
                _utc_now_iso(),
            ),
        )
        conn.commit()

        if fields.CardToken == _DEMO_TOKEN_TIMEOUT_AFTER_CREATE and settings.faults_enabled:
            # Fault injection: ödeme mock'ta kalıcı olarak oluşturuldu ("Moka tarafında
            # işlendi") ama çağıran hiçbir zaman geçerli bir ApiResponse almadı — bu
            # gerçek bir ağ timeout'unun client'a göründüğü haliyle aynı sonucu üretir
            # (§16.2 "unknown create result"). Mock yeni bir Moka ResultCode icat
            # etmediği için (§3.1) bunu transport-seviyesi bir hata olarak modelliyoruz,
            # documented bir ApiResponse zarfı olarak DEĞİL.
            _record_operation(
                conn, "DoDirectPayment", fields.OtherTrxCode, request_payload,
                {"fault": "timeout_after_create"},
            )
            raise HTTPException(
                status_code=500, detail="simulated timeout after create (fault injection)"
            )

        response = DoDirectPaymentResponse(
            Data=DoDirectPaymentData(
                IsSuccessful=True, ResultCode="", ResultMessage="",
                VirtualPosOrderId=virtual_pos_order_id,
            ),
            ResultCode="Success",
            ResultMessage="",
            Exception=None,
        )
        _record_operation(
            conn, "DoDirectPayment", fields.OtherTrxCode, request_payload,
            response.model_dump(mode="json"),
        )
        return response
    finally:
        conn.close()


# --- DoApprovePoolPayment (§2.5) ------------------------------------------


@_router.post("/PaymentDealer/DoApprovePoolPayment", response_model=DoApprovePoolPaymentResponse)
def do_approve_pool_payment(body: DoApprovePoolPaymentWireRequest) -> DoApprovePoolPaymentResponse:
    settings = MockMokaSettings.from_env()
    conn = db.connect(settings.db_path)
    try:
        request_payload = body.model_dump(mode="json")
        fields = body.PaymentDealerRequest

        def _error(result_code: str, other_trx_code: str | None) -> DoApprovePoolPaymentResponse:
            response = DoApprovePoolPaymentResponse(
                Data=None, ResultCode=result_code, ResultMessage="", Exception=None
            )
            _record_operation(
                conn, "DoApprovePoolPayment", other_trx_code, request_payload,
                response.model_dump(mode="json"),
            )
            return response

        error_code = authenticate(body.PaymentDealerAuthentication, settings)
        if error_code:
            return _error(error_code, fields.OtherTrxCode)

        if not fields.VirtualPosOrderId and not fields.OtherTrxCode:
            return _error(APPROVE_IDENTIFIER_MUST_BE_GIVEN, None)

        row = _find_by_vpos_id(conn, fields.VirtualPosOrderId) or _find_by_other_trx_code(
            conn, fields.OtherTrxCode
        )
        if row is None:
            return _error(APPROVE_DEALER_PAYMENT_NOT_FOUND, fields.OtherTrxCode)

        if not row["is_pool_payment"]:
            return _error(APPROVE_PAYMENT_IS_NOT_POOL_PAYMENT, row["other_trx_code"])

        if row["payment_status"] == status_mapper.PAYMENT_STATUS_APPROVED:
            return _error(APPROVE_PAYMENT_ALREADY_APPROVED, row["other_trx_code"])

        conn.execute(
            "UPDATE dealer_payments SET payment_status = ?, trx_status = ? WHERE other_trx_code = ?",
            (
                status_mapper.PAYMENT_STATUS_APPROVED,
                status_mapper.TRX_STATUS_APPROVED,
                row["other_trx_code"],
            ),
        )
        conn.commit()

        response = DoApprovePoolPaymentResponse(
            Data=ApproveOrUndoData(
                IsSuccessful=True,
                ResultCode="",
                ResultMessage="",
                VirtualPosOrderId=row["virtual_pos_order_id"],
            ),
            ResultCode="Success",
            ResultMessage="",
            Exception=None,
        )
        _record_operation(
            conn, "DoApprovePoolPayment", row["other_trx_code"], request_payload,
            response.model_dump(mode="json"),
        )
        return response
    finally:
        conn.close()


# --- UndoApprovePoolPayment (§2.6) ----------------------------------------


@_router.post("/PaymentDealer/UndoApprovePoolPayment", response_model=UndoApprovePoolPaymentResponse)
def undo_approve_pool_payment(
    body: UndoApprovePoolPaymentWireRequest,
) -> UndoApprovePoolPaymentResponse:
    settings = MockMokaSettings.from_env()
    conn = db.connect(settings.db_path)
    try:
        request_payload = body.model_dump(mode="json")
        fields = body.PaymentDealerRequest

        def _error(result_code: str, other_trx_code: str | None) -> UndoApprovePoolPaymentResponse:
            response = UndoApprovePoolPaymentResponse(
                Data=None, ResultCode=result_code, ResultMessage="", Exception=None
            )
            _record_operation(
                conn, "UndoApprovePoolPayment", other_trx_code, request_payload,
                response.model_dump(mode="json"),
            )
            return response

        error_code = authenticate(body.PaymentDealerAuthentication, settings)
        if error_code:
            return _error(error_code, fields.OtherTrxCode)

        if fields.VirtualPosOrderId and fields.OtherTrxCode:
            vpos_row = _find_by_vpos_id(conn, fields.VirtualPosOrderId)
            trx_row = _find_by_other_trx_code(conn, fields.OtherTrxCode)
            if vpos_row is None or trx_row is None:
                return _error(UNDO_DEALER_PAYMENT_NOT_FOUND, fields.OtherTrxCode)
            if vpos_row["other_trx_code"] != trx_row["other_trx_code"]:
                return _error(UNDO_IDENTIFIERS_NOT_MATCH, fields.OtherTrxCode)
            row = vpos_row
        elif fields.VirtualPosOrderId:
            row = _find_by_vpos_id(conn, fields.VirtualPosOrderId)
            if row is None:
                return _error(UNDO_DEALER_PAYMENT_NOT_FOUND, None)
        elif fields.OtherTrxCode:
            row = _find_by_other_trx_code(conn, fields.OtherTrxCode)
            if row is None:
                return _error(UNDO_DEALER_PAYMENT_NOT_FOUND, fields.OtherTrxCode)
        else:
            return _error(UNDO_IDENTIFIER_MUST_BE_GIVEN, None)

        if not row["is_pool_payment"]:
            return _error(UNDO_PAYMENT_IS_NOT_POOL_PAYMENT, row["other_trx_code"])

        if row["payment_status"] != status_mapper.PAYMENT_STATUS_APPROVED:
            return _error(UNDO_PAYMENT_NOT_APPROVED_YET, row["other_trx_code"])

        if row["statement_closed"]:
            # Public dokümanda exact code tanımlı değil (§2.6) — mock yeni bir Moka
            # code icat etmez; internal operation failure olarak ele alınır.
            _record_operation(
                conn, "UndoApprovePoolPayment", row["other_trx_code"], request_payload,
                {"fault": "statement_closed"},
            )
            raise HTTPException(
                status_code=409,
                detail="statement_closed: undo not permitted (undocumented Moka behavior)",
            )

        conn.execute(
            "UPDATE dealer_payments SET payment_status = ?, trx_status = ? WHERE other_trx_code = ?",
            (
                status_mapper.PAYMENT_STATUS_PENDING,
                status_mapper.TRX_STATUS_PENDING,
                row["other_trx_code"],
            ),
        )
        conn.commit()

        response = UndoApprovePoolPaymentResponse(
            Data=ApproveOrUndoData(
                IsSuccessful=True,
                ResultCode="",
                ResultMessage="",
                VirtualPosOrderId=row["virtual_pos_order_id"],
            ),
            ResultCode="Success",
            ResultMessage="",
            Exception=None,
        )
        _record_operation(
            conn, "UndoApprovePoolPayment", row["other_trx_code"], request_payload,
            response.model_dump(mode="json"),
        )
        return response
    finally:
        conn.close()


# --- GetDealerPaymentTrxDetailList (§2.7) --------------------------------


@_router.post(
    "/PaymentDealer/GetDealerPaymentTrxDetailList",
    response_model=GetDealerPaymentTrxDetailListResponse,
)
def get_dealer_payment_trx_detail_list(
    body: GetDealerPaymentTrxDetailListWireRequest,
) -> GetDealerPaymentTrxDetailListResponse:
    settings = MockMokaSettings.from_env()
    conn = db.connect(settings.db_path)
    try:
        request_payload = body.model_dump(mode="json")
        fields = body.PaymentDealerRequest

        error_code = authenticate(body.PaymentDealerAuthentication, settings)
        if error_code:
            response = GetDealerPaymentTrxDetailListResponse(
                Data=None, ResultCode=error_code, ResultMessage="", Exception=None
            )
            _record_operation(
                conn, "GetDealerPaymentTrxDetailList", fields.OtherTrxCode, request_payload,
                response.model_dump(mode="json"),
            )
            return response

        if not fields.PaymentId and not fields.OtherTrxCode:
            response = GetDealerPaymentTrxDetailListResponse(
                Data=None,
                ResultCode=AUTH_INVALID_REQUEST,
                ResultMessage="PaymentId veya OtherTrxCode zorunludur.",
                Exception=None,
            )
            _record_operation(
                conn, "GetDealerPaymentTrxDetailList", None, request_payload,
                response.model_dump(mode="json"),
            )
            return response

        row = (
            _find_by_other_trx_code(conn, fields.OtherTrxCode)
            if fields.OtherTrxCode
            else _find_by_vpos_id(conn, fields.PaymentId)
        )

        trx_list: list[PaymentTrxDetail] = []
        if row is not None:
            trx_list.append(
                PaymentTrxDetail(
                    OtherTrxCode=row["other_trx_code"],
                    VirtualPosOrderId=row["virtual_pos_order_id"],
                    PaymentStatus=row["payment_status"],
                    TrxStatus=row["trx_status"],
                )
            )

        response = GetDealerPaymentTrxDetailListResponse(
            Data=GetDealerPaymentTrxDetailListData(TrxDetailList=trx_list),
            ResultCode="Success",
            ResultMessage="",
            Exception=None,
        )
        _record_operation(
            conn, "GetDealerPaymentTrxDetailList", fields.OtherTrxCode, request_payload,
            response.model_dump(mode="json"),
        )
        return response
    finally:
        conn.close()


# --- GetPaymentList (§14.1, best-effort — bkz. schemas.py docstring) -----


@_router.post("/PaymentDealer/GetPaymentList", response_model=GetPaymentListResponse)
def get_payment_list(body: GetPaymentListWireRequest) -> GetPaymentListResponse:
    settings = MockMokaSettings.from_env()
    conn = db.connect(settings.db_path)
    try:
        request_payload = body.model_dump(mode="json")

        error_code = authenticate(body.PaymentDealerAuthentication, settings)
        if error_code:
            response = GetPaymentListResponse(
                Data=None, ResultCode=error_code, ResultMessage="", Exception=None
            )
            _record_operation(
                conn, "GetPaymentList", None, request_payload, response.model_dump(mode="json")
            )
            return response

        rows = conn.execute("SELECT * FROM dealer_payments ORDER BY created_at").fetchall()
        details = [
            PaymentTrxDetail(
                OtherTrxCode=row["other_trx_code"],
                VirtualPosOrderId=row["virtual_pos_order_id"],
                PaymentStatus=row["payment_status"],
                TrxStatus=row["trx_status"],
            )
            for row in rows
        ]
        response = GetPaymentListResponse(
            Data=GetPaymentListData(TrxDetailList=details),
            ResultCode="Success",
            ResultMessage="",
            Exception=None,
        )
        _record_operation(
            conn, "GetPaymentList", None, request_payload, response.model_dump(mode="json")
        )
        return response
    finally:
        conn.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Mock Moka PaymentDealer", version="1.0.0")

    @app.on_event("startup")
    def _startup() -> None:
        settings = MockMokaSettings.from_env()
        conn = db.connect(settings.db_path)
        try:
            db.init_db(conn)
        finally:
            conn.close()

    @app.middleware("http")
    async def _add_debug_request_id(request: Request, call_next):
        response = await call_next(request)
        # Yalnız local debug metadata'sı — Moka public contract JSON'una eklenmez (§14.5).
        response.headers["X-Mock-Moka-Request-Id"] = str(uuid4())
        return response

    app.include_router(_router)
    return app


app = create_app()
