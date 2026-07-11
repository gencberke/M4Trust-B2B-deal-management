"""FastAPI app factory — ortak middleware/handler'lar + tüm router'lar.

`startup` hook'unda migration runner çalışır; Request-ID ve yeni API hata
zarfı Plan 02 integration contract'ı olarak burada kaydedilir.
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from backend.app.db import connect, init_db
from backend.app.middleware.request_id import RequestIDMiddleware
from backend.app.routers import approvals, delivery, evidence, transactions


def create_app() -> FastAPI:
    app = FastAPI(title="M4Trust API")
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.on_event("startup")
    def _startup() -> None:
        conn = connect()
        try:
            init_db(conn)
        finally:
            conn.close()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(transactions.router)
    app.include_router(approvals.router)
    app.include_router(delivery.router)
    app.include_router(evidence.router)

    return app


app = create_app()
