"""`backend.app.api.errors` kontrat testleri — izole bir FastAPI app içinde.

Handler'lar burada `main.py`'ye değil, testin kendi kurduğu küçük app'e
kaydedilir (plan gereği: "Test the handlers using a small isolated FastAPI app
created inside tests"). Gerçek `main.py`/router'ların mevcut `HTTPException`
davranışına (409 `conflicts`, 403/404 string `detail`) bu modülün hiç
dokunmadığı ayrıca burada regresyon olarak doğrulanır.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.middleware("http")
    async def _fake_request_id(request, call_next):
        request.state.request_id = "test-request-id"
        return await call_next(request)

    @app.get("/api-error-with-detail")
    def api_error_with_detail():
        raise ApiError(
            status_code=422,
            code="SOME_VALIDATION_ERROR",
            message="Girdi geçersiz.",
            detail={"field": "amount"},
        )

    @app.get("/api-error-without-detail")
    def api_error_without_detail():
        raise ApiError(status_code=400, code="BAD_REQUEST", message="Kötü istek.")

    @app.get("/boom")
    def boom():
        raise RuntimeError("içeride patlayan gizli sır: super-secret-token-xyz")

    @app.get("/legacy-409")
    def legacy_409():
        raise HTTPException(
            status_code=409,
            detail={"code": "POLICY_LOCKED", "message": "Kilitli.", "conflicts": ["locked"]},
        )

    @app.get("/legacy-403")
    def legacy_403():
        raise HTTPException(status_code=403, detail="Geçersiz token.")

    @app.get("/legacy-404")
    def legacy_404():
        raise HTTPException(status_code=404, detail="İşlem bulunamadı.")

    return app


def _client() -> TestClient:
    return TestClient(_build_app(), raise_server_exceptions=False)


def test_api_error_serializes_standard_envelope_with_detail() -> None:
    response = _client().get("/api-error-with-detail")
    assert response.status_code == 422
    assert response.json() == {
        "code": "SOME_VALIDATION_ERROR",
        "message": "Girdi geçersiz.",
        "request_id": "test-request-id",
        "detail": {"field": "amount"},
    }


def test_api_error_omits_detail_key_when_absent() -> None:
    response = _client().get("/api-error-without-detail")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "BAD_REQUEST"
    assert body["message"] == "Kötü istek."
    assert body["request_id"] == "test-request-id"
    assert "detail" not in body


def test_unhandled_exception_is_sanitized() -> None:
    response = _client().get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body == {
        "code": "INTERNAL_ERROR",
        "message": "Beklenmeyen bir hata oluştu.",
        "request_id": "test-request-id",
    }
    # Ham istisna mesajı (secret içerir) hiçbir şekilde gövdeye sızmamalı.
    assert "super-secret-token-xyz" not in response.text
    assert "RuntimeError" not in response.text


def test_legacy_409_conflicts_body_untouched() -> None:
    response = _client().get("/legacy-409")
    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "POLICY_LOCKED", "message": "Kilitli.", "conflicts": ["locked"]}
    }


def test_legacy_403_string_detail_untouched() -> None:
    response = _client().get("/legacy-403")
    assert response.status_code == 403
    assert response.json() == {"detail": "Geçersiz token."}


def test_legacy_404_string_detail_untouched() -> None:
    response = _client().get("/legacy-404")
    assert response.status_code == 404
    assert response.json() == {"detail": "İşlem bulunamadı."}


def test_api_error_without_request_id_in_state_returns_null() -> None:
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)

    @app.get("/no-request-id")
    def no_request_id():
        raise ApiError(status_code=400, code="BAD_REQUEST", message="Kötü istek.")

    response = TestClient(app, raise_server_exceptions=False).get("/no-request-id")
    body = response.json()
    assert body["request_id"] is None
