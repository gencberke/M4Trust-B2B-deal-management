"""FastAPI app factory — `/health` + transactions/approvals router'ları (Faz 3B).

`startup` hook'unda `init_db()` çalışır: uygulama ayağa kalktığında altı
tablo (§5) hazır olur. Delivery/evidence router'ları (Faz 4) henüz eklenmedi.
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.db import connect, init_db
from backend.app.routers import approvals, transactions


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

    return app


app = create_app()
