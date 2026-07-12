"""Rate limiting, lockout, reset and verification semantics (Plan 09)."""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from sqlite3 import Connection

from fastapi import Request

from backend.app.api.errors import ApiError
from backend.app.config import Settings
from backend.app.repositories import auth_tokens as token_repo
from backend.app.repositories import users as users_repo
from backend.app.services import audit
from backend.app.services.auth import hash_password, hash_token, normalize_email, now_iso

PASSWORD_RESET = "password_reset"
EMAIL_VERIFICATION = "email_verification"
_GENERIC_TOKEN_ERROR = "Token geçersiz veya süresi dolmuş."


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def consume(self, key: str, *, limit: int, window_seconds: float) -> float | None:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return max(0.0, window_seconds - (now - events[0]))
            events.append(now)
        return None

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


_limiter = SlidingWindowLimiter()


def reset_rate_limit_state_for_tests() -> None:
    _limiter.clear()


def _client_ip(request: Request, *, trust_proxy_headers: bool) -> str:
    candidate = request.client.host if request.client is not None else "unknown"
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            try:
                candidate = str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
    return candidate


def _opaque_key(scope: str, request: Request, identity: str, settings: Settings) -> str:
    material = (
        f"{scope}|{_client_ip(request, trust_proxy_headers=settings.trust_proxy_headers)}|"
        f"{normalize_email(identity)}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    identity: str,
    limit: int,
    window_seconds: float,
    settings: Settings,
) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    retry_after = _limiter.consume(
        _opaque_key(scope, request, identity, settings),
        limit=limit,
        window_seconds=window_seconds,
    )
    if retry_after is not None:
        raise ApiError(
            status_code=429,
            code="AUTH_RATE_LIMITED",
            message="Çok fazla istek. Lütfen daha sonra tekrar deneyin.",
            detail={"retry_after_seconds": max(1, int(retry_after))},
        )


def is_account_locked(row) -> bool:
    locked_until = row["locked_until"]
    if not locked_until:
        return False
    return datetime.fromisoformat(locked_until) > datetime.now(timezone.utc)


def record_login_failure(
    conn: Connection,
    row,
    *,
    settings: Settings,
    request_id: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    window_started = row["failed_login_window_started_at"]
    count = int(row["failed_login_count"] or 0)
    if (
        not window_started
        or now - datetime.fromisoformat(window_started)
        >= timedelta(seconds=settings.account_lockout_window_seconds)
    ):
        count = 1
        window_started = now.isoformat()
    else:
        count += 1
    locked_until = None
    if count >= settings.account_lockout_threshold:
        locked_until = (now + timedelta(seconds=settings.account_lockout_seconds)).isoformat()
    conn.execute(
        "UPDATE users SET failed_login_count=?, failed_login_window_started_at=?, "
        "locked_until=?, updated_at=? WHERE id=?",
        (count, window_started, locked_until, now.isoformat(), row["id"]),
    )
    if locked_until:
        audit.record(
            conn,
            audit.AuditActor(actor_type="anonymous", request_id=request_id),
            "auth.account_locked",
            f"user:{row['id']}",
            frozenset({"failure_count", "lock_state"}),
            metadata={"failure_count": count, "lock_state": "locked"},
        )


def clear_login_failures(conn: Connection, *, user_id: str) -> None:
    conn.execute(
        "UPDATE users SET failed_login_count=0, failed_login_window_started_at=NULL, "
        "locked_until=NULL, updated_at=? WHERE id=?",
        (now_iso(), user_id),
    )


def issue_action_token(
    conn: Connection,
    *,
    user_id: str,
    purpose: str,
    ttl_seconds: float,
) -> str:
    raw = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    token_repo.invalidate_unused(conn, user_id=user_id, purpose=purpose, now=now.isoformat())
    token_repo.insert(
        conn,
        user_id=user_id,
        purpose=purpose,
        token_hash=hash_token(raw),
        expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(),
        now=now.isoformat(),
    )
    return raw


def consume_action_token(conn: Connection, *, raw_token: str, purpose: str):
    row = token_repo.get_by_hash(conn, token_hash=hash_token(raw_token), purpose=purpose)
    now = datetime.now(timezone.utc)
    if (
        row is None
        or row["used_at"] is not None
        or datetime.fromisoformat(row["expires_at"]) <= now
        or not token_repo.consume_if_unused(conn, token_id=row["id"], now=now.isoformat())
    ):
        raise ApiError(status_code=400, code="AUTH_TOKEN_INVALID", message=_GENERIC_TOKEN_ERROR)
    return row


def complete_password_reset(
    conn: Connection, *, raw_token: str, new_password: str
) -> str:
    token = consume_action_token(conn, raw_token=raw_token, purpose=PASSWORD_RESET)
    conn.execute(
        "UPDATE users SET password_hash=?, failed_login_count=0, "
        "failed_login_window_started_at=NULL, locked_until=NULL, updated_at=? WHERE id=?",
        (hash_password(new_password), now_iso(), token["user_id"]),
    )
    users_repo.revoke_all_sessions_for_user(conn, user_id=token["user_id"], now=now_iso())
    audit.record(
        conn,
        audit.AuditActor(actor_type="system"),
        "auth.password_reset_completed",
        f"user:{token['user_id']}",
        frozenset({"result"}),
        metadata={"result": "completed"},
    )
    return token["user_id"]


def complete_email_verification(conn: Connection, *, raw_token: str) -> str:
    token = consume_action_token(conn, raw_token=raw_token, purpose=EMAIL_VERIFICATION)
    verified_at = now_iso()
    conn.execute(
        "UPDATE users SET email_verified_at=COALESCE(email_verified_at, ?), updated_at=? "
        "WHERE id=?",
        (verified_at, verified_at, token["user_id"]),
    )
    audit.record(
        conn,
        audit.AuditActor(actor_type="system"),
        "auth.email_verified",
        f"user:{token['user_id']}",
        frozenset({"result"}),
        metadata={"result": "verified"},
    )
    return token["user_id"]
