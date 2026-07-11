"""Standart API hata zarfı — `{code, message, request_id, detail?}`.

Bağlayıcı olduğu kapsam yalnız (a) bu modülün `ApiError`'ı ile **yeni açıkça
fırlatılan** hatalar ve (b) **yakalanmamış** istisnalardır. Mevcut uçların
`fastapi.HTTPException` kullanımı (409 `conflicts` gövdeleri, 403/404 string
`detail`'ler, H0 teslimat-kanıtı yetkilendirmesi, Moka mock zarfları) bu
modülden hiçbir şekilde etkilenmez: burada `HTTPException` için handler
tanımlanmaz, mevcut endpoint sözleşmeleri global olarak yeniden yazılmaz.

Bu dosya `main.py`'ye kaydedilmez — kayıt (`app.add_exception_handler(...)`)
Berke'nin entegrasyon commit'idir (bkz. program_haritasi §3, Revizyon #3).
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

_INTERNAL_ERROR_CODE = "INTERNAL_ERROR"
_INTERNAL_ERROR_MESSAGE = "Beklenmeyen bir hata oluştu."


class ApiError(Exception):
    """Yeni uçların standart zarfla fırlatacağı hata.

    Mevcut `HTTPException` tabanlı uçlar bunu kullanmaz — geriye dönük davranış
    korunur; yalnızca Plan 03+ ile eklenecek yeni uçlar için bağlayıcıdır.
    """

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def build_error_body(
    *,
    code: str,
    message: str,
    request_id: str | None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`{code, message, request_id, detail?}` — `detail` yalnız verilmişse eklenir."""
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if detail is not None:
        body["detail"] = detail
    return body


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    body = build_error_body(
        code=exc.code,
        message=exc.message,
        request_id=_request_id(request),
        detail=exc.detail,
    )
    return JSONResponse(status_code=exc.status_code, content=body)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Yakalanmamış her istisna için sabit, sızıntısız gövde.

    `exc` mesajı, tipi veya traceback'i gövdeye asla yazılmaz — yalnız
    request_id ile ilişkilendirilebilir jenerik bir hata döner.
    """
    body = build_error_body(
        code=_INTERNAL_ERROR_CODE,
        message=_INTERNAL_ERROR_MESSAGE,
        request_id=_request_id(request),
        detail=None,
    )
    return JSONResponse(status_code=500, content=body)
