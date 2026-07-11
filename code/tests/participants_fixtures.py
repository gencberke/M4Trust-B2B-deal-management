"""Plan 03 / Faz 3B domain fixture'ları — participants/invitations/audit testleri.

`extraction_fixtures.py` ile aynı kalıp: paylaşılan ama domain-özel yardımcılar
`conftest.py`'ye değil buraya konur (conftest yalnız gerçekten ortak StubActor/
isolated_db/client altyapısını taşır).

3A (`users`/`memberships`, migration 003/004) bu branch'te henüz YOK — burada
kurulan `users`/`memberships` tabloları yalnız v2 §5.1/§5.4'ün dondurulmuş
kolon sözleşmesini (id/email_normalized; user_id/legal_entity_id/status)
taklit eden TEST-ÖZEL stub'lardır. `repositories/participants.py`'nin dar SQL
yardımcıları (`get_user_email_normalized`/`has_active_membership`) bu stub'lara
karşı da, Berke'nin gerçek 3A tablolarına karşı da aynı şekilde çalışır --
sözleşme yalnızca kolon adlarına bağlıdır.
"""

from __future__ import annotations

import sqlite3
from importlib import import_module
from uuid import uuid4

_baseline = import_module("backend.app.db.migrations.001_baseline_current_schema")
_participants_migration = import_module(
    "backend.app.db.migrations.005_participants_invitations"
)
_audit_migration = import_module("backend.app.db.migrations.006_audit_events")


def make_participants_db() -> sqlite3.Connection:
    """001 + 005 + 006 uygulanmış, foreign_keys=ON bellek-içi bağlantı + stub
    `users`/`memberships` tabloları."""
    # `check_same_thread=False`: TestClient, ASGI app'i ayrı bir worker
    # thread'inde çalıştırır (`anyio.to_thread`) -- router testlerinde bu
    # bağlantı o thread'den de kullanılır (gerçek `db/connection.py::connect()`
    # ile aynı ayar).
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    _baseline.apply(conn)
    _participants_migration.apply(conn)
    _audit_migration.apply(conn)

    conn.execute(
        """CREATE TABLE users (
            id TEXT PRIMARY KEY,
            email_normalized TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active'
        )"""
    )
    conn.execute(
        """CREATE TABLE memberships (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            legal_entity_id TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        )"""
    )
    conn.commit()
    return conn


def create_test_transaction(conn: sqlite3.Connection, *, transaction_id: str | None = None) -> str:
    """001 baseline `transactions` tablosuna minimal bir satır ekler (yalnız FK
    hedefi olarak; içerik/extraction bu testlerin konusu değil)."""
    transaction_id = transaction_id or uuid4().hex
    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, markdown, "
        "masked_markdown, created_at, manager_token) VALUES (?, 'awaiting_approval', "
        "'buyer-tok', 'seller-tok', '', '', datetime('now'), 'manager-tok')",
        (transaction_id,),
    )
    return transaction_id


def create_test_user(
    conn: sqlite3.Connection, *, email_normalized: str, user_id: str | None = None, status: str = "active"
) -> str:
    user_id = user_id or uuid4().hex
    conn.execute(
        "INSERT INTO users (id, email_normalized, status) VALUES (?, ?, ?)",
        (user_id, email_normalized, status),
    )
    return user_id


def create_test_membership(
    conn: sqlite3.Connection, *, user_id: str, legal_entity_id: str, role: str = "owner", status: str = "active"
) -> str:
    membership_id = uuid4().hex
    conn.execute(
        "INSERT INTO memberships (id, user_id, legal_entity_id, role, status) VALUES (?, ?, ?, ?, ?)",
        (membership_id, user_id, legal_entity_id, role, status),
    )
    return membership_id


def build_isolated_app(conn: sqlite3.Connection, actor_context, *, notification_provider=None):
    """Yalnız invitations/participants router'larını içeren izole FastAPI app.

    Plan 02'nin error handler + request-id middleware kontratını kullanır
    (bkz. `main.py`); `get_db` verilen `conn`'u yeniden kullanır ve **kapatmaz**
    (test'in kendi fixture'ı bağlantının ömrünü yönetir) -- gerçek `get_db`nin
    aksine, aynı connection birden çok istekte tekrar kullanılabilsin diye.
    """
    from fastapi import FastAPI

    from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
    from backend.app.db import get_db
    from backend.app.middleware.request_id import RequestIDMiddleware
    from backend.app.routers import invitations as invitations_router
    from backend.app.routers import participants as participants_router
    from backend.app.services.access_control import get_current_actor

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(invitations_router.router)
    app.include_router(participants_router.router)

    def _get_db():
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_actor] = lambda: actor_context
    if notification_provider is not None:
        app.dependency_overrides[invitations_router.get_notification_provider] = (
            lambda: notification_provider
        )

    return app
