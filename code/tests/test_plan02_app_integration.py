"""Plan 02 middleware ve hata handler'larının app-factory wiring testi."""

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
