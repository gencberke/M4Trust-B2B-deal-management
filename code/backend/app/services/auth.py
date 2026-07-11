"""Parola/oturum/CSRF servisi (Faz 3A).

Argon2id parola hash'i, random session/CSRF token üretimi (DB'de yalnız
SHA-256 hash), throttled `last_seen_at` güncellemesi ve CSRF/Origin
doğrulaması burada yaşar. `access_control.py::get_current_actor`, session
cookie'sini bu modülün `resolve_session_principal()` fonksiyonu ile çözer.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from sqlite3 import Connection

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError
from fastapi import Depends, Request

from backend.app.api.errors import ApiError
from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.repositories import users as users_repo

_GENERIC_LOGIN_ERROR = "E-posta veya parola hatalı."
_SESSION_TOKEN_BYTES = 32
_CSRF_TOKEN_BYTES = 32
_LAST_SEEN_THROTTLE_SECONDS = 60
_CSRF_HEADER_NAME = "X-CSRF-Token"

SESSION_COOKIE_NAME = "m4t_session"
CSRF_COOKIE_NAME = "m4t_csrf"

_hasher = PasswordHasher()
_DUMMY_PASSWORD_HASH = _hasher.hash(secrets.token_hex(16))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHash):
        return False


def _random_token() -> str:
    return secrets.token_urlsafe(_SESSION_TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def register_user(
    conn: Connection,
    *,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
) -> str:
    normalized = normalize_email(email)
    if users_repo.get_user_by_email(conn, normalized) is not None:
        raise ApiError(
            status_code=409,
            code="EMAIL_ALREADY_REGISTERED",
            message="Bu e-posta ile zaten bir hesap var.",
        )
    password_hash = hash_password(password)
    return users_repo.insert_user(
        conn,
        email_normalized=normalized,
        password_hash=password_hash,
        first_name=first_name,
        last_name=last_name,
        now=now_iso(),
    )


def authenticate_user(conn: Connection, *, email: str, password: str):
    normalized = normalize_email(email)
    row = users_repo.get_user_by_email(conn, normalized)
    if row is None:
        # Bilinmeyen e-postada da hash doğrulaması çalıştırılır: kullanıcı
        # var/yok bilgisini zamanlama farkıyla sızdırmamak için gerçek bir
        # Argon2 hash'ine karşı maliyetli bir doğrulama yapılır (sonucu
        # kullanılmaz).
        verify_password(_DUMMY_PASSWORD_HASH, password)
        raise ApiError(status_code=401, code="INVALID_CREDENTIALS", message=_GENERIC_LOGIN_ERROR)
    if row["status"] != "active":
        raise ApiError(status_code=401, code="INVALID_CREDENTIALS", message=_GENERIC_LOGIN_ERROR)
    if not verify_password(row["password_hash"], password):
        raise ApiError(status_code=401, code="INVALID_CREDENTIALS", message=_GENERIC_LOGIN_ERROR)
    return row


@dataclass(frozen=True, slots=True)
class IssuedSession:
    session_id: str
    raw_token: str
    raw_csrf_token: str
    expires_at: datetime


def create_session(conn: Connection, *, user_id: str, settings: Settings) -> IssuedSession:
    raw_token = _random_token()
    raw_csrf_token = _random_token()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds)
    session_id = users_repo.insert_session(
        conn,
        user_id=user_id,
        token_hash=hash_token(raw_token),
        csrf_token_hash=hash_token(raw_csrf_token),
        expires_at=expires_at.isoformat(),
        now=now_iso(),
    )
    return IssuedSession(
        session_id=session_id,
        raw_token=raw_token,
        raw_csrf_token=raw_csrf_token,
        expires_at=expires_at,
    )


def revoke_session_by_token(conn: Connection, *, raw_token: str) -> bool:
    row = users_repo.get_session_by_token_hash(conn, hash_token(raw_token))
    if row is None:
        return False
    users_repo.revoke_session(conn, session_id=row["id"], now=now_iso())
    return True


def revoke_all_sessions(conn: Connection, *, user_id: str) -> int:
    return users_repo.revoke_all_sessions_for_user(conn, user_id=user_id, now=now_iso())


@dataclass(frozen=True, slots=True)
class SessionPrincipal:
    session_id: str
    user_id: str
    platform_role: str | None
    csrf_token_hash: str


def resolve_session_principal(conn: Connection, raw_token: str) -> SessionPrincipal | None:
    """Geçerli (revoke edilmemiş, süresi dolmamış, aktif user'a ait) session'ı çözer.

    Yan etki: `last_seen_at`, önceki yazımdan en az 60 saniye geçmişse
    güncellenir (throttled write) ve `conn.commit()` çağrılır.
    """

    session_row = users_repo.get_session_by_token_hash(conn, hash_token(raw_token))
    if session_row is None or session_row["revoked_at"] is not None:
        return None
    if _parse_iso(session_row["expires_at"]) <= datetime.now(timezone.utc):
        return None
    user_row = users_repo.get_user_by_id(conn, session_row["user_id"])
    if user_row is None or user_row["status"] != "active":
        return None

    _maybe_touch_last_seen(conn, session_row)

    return SessionPrincipal(
        session_id=session_row["id"],
        user_id=user_row["id"],
        platform_role=user_row["platform_role"],
        csrf_token_hash=session_row["csrf_token_hash"],
    )


def _maybe_touch_last_seen(conn: Connection, session_row) -> None:
    last_seen_at = session_row["last_seen_at"]
    now = datetime.now(timezone.utc)
    if last_seen_at is not None:
        elapsed = (now - _parse_iso(last_seen_at)).total_seconds()
        if elapsed < _LAST_SEEN_THROTTLE_SECONDS:
            return
    users_repo.touch_last_seen(conn, session_id=session_row["id"], now=now.isoformat())
    conn.commit()


def raw_session_token_from_request(request: Request, *, cookie_name: str) -> str | None:
    return request.cookies.get(cookie_name)


def verify_csrf(
    conn: Connection,
    *,
    request: Request,
    session_cookie_name: str = SESSION_COOKIE_NAME,
) -> None:
    """Mutating, session-authenticated istekler için CSRF/Origin doğrulaması.

    Session cookie yoksa doğrulama yapılmaz (bu durumda çağıran endpoint zaten
    `require_authenticated_user` ile 401 döner). Session cookie varsa:
    * `X-CSRF-Token` header'ı zorunludur ve saklanan hash'le sabit-zamanlı
      karşılaştırılır,
    * `Origin` header'ı verilmişse istek host'uyla aynı olmalıdır.
    """

    raw_token = raw_session_token_from_request(request, cookie_name=session_cookie_name)
    if raw_token is None:
        return

    principal = resolve_session_principal(conn, raw_token)
    if principal is None:
        return

    origin = request.headers.get("origin")
    if origin is not None:
        origin_host = origin.split("://", 1)[-1].split("/", 1)[0]
        request_host = request.headers.get("host", "")
        if origin_host != request_host:
            raise ApiError(
                status_code=403,
                code="CSRF_ORIGIN_MISMATCH",
                message="İstek kaynağı doğrulanamadı.",
            )

    provided = request.headers.get(_CSRF_HEADER_NAME)
    if not provided or not hmac.compare_digest(hash_token(provided), principal.csrf_token_hash):
        raise ApiError(
            status_code=403,
            code="CSRF_TOKEN_INVALID",
            message="CSRF token eksik veya geçersiz.",
        )


def require_csrf_protection(request: Request, conn: Connection = Depends(get_db)) -> None:
    """Mutating route'larda `Depends` olarak kullanılacak CSRF guard'ı.

    `get_db` request-scoped bağlantısını paylaşır (FastAPI dependency cache'i
    sayesinde router'ın kendi `Depends(get_db)`'siyle aynı connection).
    """

    verify_csrf(conn, request=request)
