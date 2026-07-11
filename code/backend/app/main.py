"""FastAPI app factory — ortak middleware/handler'lar + tüm router'lar.

`startup` hook'unda migration runner çalışır; Request-ID ve yeni API hata
zarfı Plan 02 integration contract'ı olarak burada kaydedilir. Plan 03
(Faz 3A/3B/3C) router kayıtları — `auth`/`entities`/`participants`/
`invitations` — bu entegrasyon checkpoint'inde eklendi (program_haritasi §3,
Revizyon #3: router kayıtları Berke'nin entegrasyon commit'idir). Plan 04
Wave A kapanışında `reviews`, Faz 4F-1'de `rule_sets` router'ı da aynı
app-factory wiring'ine eklendi.
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from backend.app.db import connect, init_db
from backend.app.middleware.request_id import RequestIDMiddleware
from backend.app.routers import (
    approvals,
    auth,
    delivery,
    entities,
    evidence,
    invitations,
    participants,
    ratifications,
    reviews,
    rule_sets,
    transactions,
)


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
    app.include_router(auth.router)
    app.include_router(entities.router)
    app.include_router(participants.router)
    app.include_router(invitations.router)
    app.include_router(reviews.router)
    app.include_router(rule_sets.router)
    app.include_router(ratifications.router)

    return app


app = create_app()
