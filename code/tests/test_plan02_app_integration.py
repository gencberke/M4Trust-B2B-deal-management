"""Plan 02 middleware ve hata handler'larının app-factory wiring testi."""

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from backend.app.main import create_app
from backend.app.middleware.request_id import RequestIDMiddleware


def test_app_factory_registers_plan02_contracts() -> None:
    app = create_app()

    assert app.exception_handlers[ApiError] is api_error_handler
    assert app.exception_handlers[Exception] is unhandled_exception_handler
    assert any(middleware.cls is RequestIDMiddleware for middleware in app.user_middleware)


def test_health_response_includes_request_id_without_body_change() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_unhandled_500_has_sanitized_body_and_matching_request_id_header() -> None:
    app = create_app()

    @app.get("/_test/unhandled")
    def _unhandled() -> None:
        raise RuntimeError("secret-token request-body and private@example.test")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/unhandled", headers={"X-Request-ID": "integration-req-500"})

    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "message": "Beklenmeyen bir hata oluştu.",
        "request_id": "integration-req-500",
    }
    assert response.headers["X-Request-ID"] == response.json()["request_id"]
    assert "RuntimeError" not in response.text
    assert "secret-token" not in response.text
    assert "request-body" not in response.text
    assert "private@example.test" not in response.text


def test_real_app_legacy_http_exception_body_remains_unchanged() -> None:
    app = create_app()

    @app.get("/_test/legacy-409")
    def _legacy_409() -> None:
        raise HTTPException(
            status_code=409,
            detail={"code": "POLICY_LOCKED", "message": "Kilitli.", "conflicts": ["locked"]},
        )

    with TestClient(app) as client:
        forbidden = client.get("/api/transactions")
        missing = client.get("/api/transactions/does-not-exist")
        conflict = client.get("/_test/legacy-409")

    assert forbidden.status_code == 403
    assert forbidden.json() == {"detail": "Liste erişimi kapalı."}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "İşlem bulunamadı."}
    assert conflict.status_code == 409
    assert conflict.json() == {
        "detail": {"code": "POLICY_LOCKED", "message": "Kilitli.", "conflicts": ["locked"]}
    }
