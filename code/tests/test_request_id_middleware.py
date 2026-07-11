"""`backend.app.middleware.request_id` kontrat testleri — izole bir FastAPI app içinde."""

from __future__ import annotations

import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.middleware.request_id import RequestIDMiddleware

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.exception_handler(RuntimeError)
    async def _boom_handler(request: Request, exc: RuntimeError) -> JSONResponse:
        # Gerçek entegrasyonda bu rolü `api/errors.py::unhandled_exception_handler`
        # oynar; burada yalnız "handler request_id'yi görebiliyor mu" doğrulanır.
        return JSONResponse(status_code=500, content={"error": "boom"})

    @app.get("/echo")
    def echo(request: Request):
        return {"request_id": request.state.request_id}

    @app.get("/boom")
    def boom(request: Request):
        assert request.state.request_id is not None
        raise RuntimeError("boom")

    return app


def _client() -> TestClient:
    return TestClient(_build_app(), raise_server_exceptions=False)


def test_generated_id_is_hex_and_consistent_across_header_and_state() -> None:
    response = _client().get("/echo")
    assert response.status_code == 200
    header_id = response.headers["X-Request-ID"]
    assert _HEX32.fullmatch(header_id)
    assert response.json()["request_id"] == header_id


def test_every_response_has_request_id_header() -> None:
    response = _client().get("/echo")
    assert "X-Request-ID" in response.headers


def test_inbound_valid_id_is_preserved() -> None:
    response = _client().get("/echo", headers={"X-Request-ID": "client-supplied-id-123"})
    assert response.headers["X-Request-ID"] == "client-supplied-id-123"
    assert response.json()["request_id"] == "client-supplied-id-123"


def test_inbound_overlong_id_is_replaced_with_generated_id() -> None:
    overlong = "a" * 500
    response = _client().get("/echo", headers={"X-Request-ID": overlong})
    header_id = response.headers["X-Request-ID"]
    assert header_id != overlong
    assert _HEX32.fullmatch(header_id)


def test_inbound_control_character_id_is_replaced_with_generated_id() -> None:
    # httpx başlık değerlerinde \r\n'e izin vermez; \x00 gömerek kontrol karakteri simüle ederiz.
    malformed = "abc\x00def"
    response = _client().get("/echo", headers={"X-Request-ID": malformed})
    header_id = response.headers["X-Request-ID"]
    assert header_id != malformed
    assert _HEX32.fullmatch(header_id)


def test_inbound_id_with_disallowed_characters_is_replaced() -> None:
    response = _client().get("/echo", headers={"X-Request-ID": "not valid/with slash"})
    header_id = response.headers["X-Request-ID"]
    assert header_id != "not valid/with slash"
    assert _HEX32.fullmatch(header_id)


def test_error_responses_still_carry_request_id_header() -> None:
    response = _client().get("/boom")
    assert response.status_code == 500
    assert "X-Request-ID" in response.headers
    assert _HEX32.fullmatch(response.headers["X-Request-ID"])


def test_two_requests_get_different_generated_ids() -> None:
    client = _client()
    first = client.get("/echo").headers["X-Request-ID"]
    second = client.get("/echo").headers["X-Request-ID"]
    assert first != second
