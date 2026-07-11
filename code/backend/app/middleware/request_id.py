"""Request-ID middleware — her isteğe tek bir kimlik atar.

Kural: `request.state.request_id` her zaman dolu olur (`api/errors.py` ve
gelecekteki audit kodu bunu okur); her cevapta `X-Request-ID` header'ı bulunur.
Gelen `X-Request-ID` header'ı sınırsız uzunlukta veya kontrol karakterli ise
KABUL EDİLMEZ — yerine yeni bir kimlik üretilir (baş harf enjeksiyonu / log
zehirleme riskine karşı). Middleware istek gövdesini okumaz, hiçbir içerik
sızdırmaz.

Bu modül `main.py`'ye kaydedilmez — kayıt Berke'nin entegrasyon commit'idir
(bkz. program_haritasi §3).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

_INBOUND_HEADER_NAME = b"x-request-id"
_RESPONSE_HEADER_NAME = b"x-request-id"
_MAX_INBOUND_LENGTH = 128
_VALID_INBOUND_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,%d}$" % _MAX_INBOUND_LENGTH)


def generate_request_id() -> str:
    return uuid.uuid4().hex


def _is_valid_inbound_id(value: str) -> bool:
    return bool(_VALID_INBOUND_PATTERN.fullmatch(value))


def _extract_inbound_id(scope: Scope) -> str | None:
    for raw_name, raw_value in scope.get("headers", ()):
        if raw_name.lower() == _INBOUND_HEADER_NAME:
            try:
                return raw_value.decode("ascii")
            except UnicodeDecodeError:
                return None
    return None


class RequestIDMiddleware:
    """`request.state.request_id` + `X-Request-ID` cevap header'ı için ASGI middleware."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        inbound = _extract_inbound_id(scope)
        request_id = inbound if inbound and _is_valid_inbound_id(inbound) else generate_request_id()

        state: dict[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((_RESPONSE_HEADER_NAME, request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        await self._app(scope, receive, send_wrapper)
