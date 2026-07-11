"""Plan 04 / Wave A / Faz 4B domain fixture'ları — review_cases/review_actions testleri.

`participants_fixtures.py` ile aynı kalıp: paylaşılan ama domain-özel
yardımcılar `conftest.py`'ye değil buraya konur.
"""

from __future__ import annotations

import sqlite3
from importlib import import_module

_baseline = import_module("backend.app.db.migrations.001_baseline_current_schema")
_identity_migration = import_module("backend.app.db.migrations.003_identity_sessions")
_entities_migration = import_module("backend.app.db.migrations.004_legal_entities_memberships")
_participants_migration = import_module("backend.app.db.migrations.005_participants_invitations")
_audit_migration = import_module("backend.app.db.migrations.006_audit_events")
_review_migration = import_module("backend.app.db.migrations.010_review_cases")


def make_reviews_db() -> sqlite3.Connection:
    """001 + 006 + 010 uygulanmış, foreign_keys=ON bellek-içi bağlantı.

    006 (`audit_events`) dahildir çünkü `services/review.py`'nin her mutation'ı
    `audit.record()` çağırır -- tablo yoksa bu çağrılar patlar.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    _baseline.apply(conn)
    _audit_migration.apply(conn)
    _review_migration.apply(conn)
    conn.commit()
    return conn


def make_full_reviews_db(db_path: str | None = None) -> sqlite3.Connection:
    """001 + 003 + 004 + 005 + 006 + 010 -- gerçek session/CSRF akışını
    (`services/auth.py`) uçtan uca test edebilmek için `users`/`sessions`/
    `legal_entities`/`memberships` gerçek 3A şemasıyla dahildir.

    `db_path` verilirse (gerçek dosya) `:memory:` yerine o dosyaya bağlanır --
    `services.access_control._resolve_session_actor`, `Depends(get_db)`
    ÜZERİNDEN DEĞİL doğrudan `backend.app.db.connect()` (yeni bir bağlantı,
    `DB_PATH` env'ini okur) ile session'ı çözer; bu yüzden CSRF/session
    testlerinde `:memory:` iki farklı (görünmez) veritabanı gibi davranır.
    Gerçek dosya + `DB_PATH` env eşleşmesi bu ayrımı ortadan kaldırır.
    """
    conn = sqlite3.connect(db_path or ":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    _baseline.apply(conn)
    _identity_migration.apply(conn)
    _entities_migration.apply(conn)
    _participants_migration.apply(conn)
    _audit_migration.apply(conn)
    _review_migration.apply(conn)
    conn.commit()
    return conn


def create_real_user(
    conn: sqlite3.Connection,
    *,
    email_normalized: str,
    platform_role: str | None = None,
    user_id: str | None = None,
) -> str:
    """Gerçek `users` tablosuna (003) satır ekler -- `services.auth.register_user`'ı
    tekrar yazmadan, doğrudan SQL ile (parola bu testlerde önemsizdir)."""
    from uuid import uuid4

    user_id = user_id or uuid4().hex
    conn.execute(
        "INSERT INTO users (id, email_normalized, password_hash, first_name, last_name, "
        "status, platform_role, created_at, updated_at) VALUES (?, ?, 'unused-hash', 'Test', "
        "'User', 'active', ?, datetime('now'), datetime('now'))",
        (user_id, email_normalized, platform_role),
    )
    return user_id


def create_real_session(conn: sqlite3.Connection, *, user_id: str):
    """Gerçek `services.auth.create_session`'ı çağırır -- dönen `IssuedSession.raw_token`/
    `raw_csrf_token` test client'ta cookie/header olarak kullanılır."""
    from backend.app.config import Settings
    from backend.app.services.auth import create_session

    return create_session(conn, user_id=user_id, settings=Settings.from_env())


def build_reviews_app(conn: sqlite3.Connection, actor_context=None):
    """Yalnız reviews router'ını içeren izole FastAPI app.

    `actor_context` verilirse `get_current_actor` StubActor ile override edilir
    (business-logic/authorization testleri için hızlı yol -- gerçek session
    cookie'si olmadığından `require_csrf_protection` otomatik no-op'tur).
    `actor_context=None` bırakılırsa GERÇEK `get_current_actor` (session-cookie
    çözümü) devrededir -- CSRF/Origin testleri bunu kullanır (`SESSION_COOKIE_NAME`/
    `X-CSRF-Token` gerçek değerlerle set edilmelidir).
    """
    from fastapi import FastAPI

    from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
    from backend.app.db import get_db
    from backend.app.middleware.request_id import RequestIDMiddleware
    from backend.app.routers import reviews as reviews_router
    from backend.app.services.access_control import get_current_actor

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(reviews_router.router)

    def _get_db():
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()

    app.dependency_overrides[get_db] = _get_db
    if actor_context is not None:
        app.dependency_overrides[get_current_actor] = lambda: actor_context

    return app
