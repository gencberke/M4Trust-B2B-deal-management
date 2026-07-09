"""FastAPI app factory — `/health` + tüm router'lar (Faz 3B + Faz 4B).

`startup` hook'unda `init_db()` çalışır: uygulama ayağa kalktığında altı
tablo (§5) hazır olur.
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.db import connect, init_db
from backend.app.routers import approvals, delivery, evidence, transactions


def create_app() -> FastAPI:
    app = FastAPI(title="M4Trust API")

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
