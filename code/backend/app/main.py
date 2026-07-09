"""FastAPI app factory (Faz 1) — yalnızca `/health`; router'lar sonraki fazlarda eklenir.

`startup` hook'unda `init_db()` çalışır: uygulama ayağa kalktığında altı
tablo (§5) hazır olur. Bu dosya bilerek minimal tutulur — Faz 1 scope'u
yalnızca app iskeleti + DB kurulumudur (validator/router'lar dahil değil).
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.db import connect, init_db


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

    return app


app = create_app()
