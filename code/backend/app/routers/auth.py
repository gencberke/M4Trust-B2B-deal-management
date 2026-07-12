"""Auth router — register/login/logout/me/session revoke (Faz 3A, §14).

Bu router `main.py`'ye Plan 03 integration checkpoint'inde kaydedilir (§3,
Revizyon #3); burada yalnız tanımlanır. Business hataları `ApiError` (§Plan 02)
ile döner; access-control guard'ları (`require_authenticated_user`) frozen
`HTTPException` davranışını korur.
"""

from __future__ import annotations

from sqlite3 import Connection
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.repositories import users as users_repo
from backend.app.api.errors import ApiError
from backend.app.schemas.identity import (
    EmailVerificationConfirm,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    UserPublic,
)
from backend.app.services import auth as auth_service
from backend.app.services import auth_hardening
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.notifications import (
    NotificationDeliveryError,
    NotificationProvider,
    make_notification_provider,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
def get_auth_notification_provider() -> NotificationProvider:
    return make_notification_provider()


def _settings() -> Settings:
    return Settings.from_env()


def _user_public(row) -> UserPublic:
    return UserPublic(
        id=row["id"],
        email=row["email_normalized"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        status=row["status"],
        platform_role=row["platform_role"],
        email_verified_at=row["email_verified_at"],
        created_at=row["created_at"],
    )


def _set_session_cookies(
    response: Response, *, raw_token: str, raw_csrf_token: str, settings: Settings
) -> None:
    max_age = int(settings.session_ttl_seconds)
    response.set_cookie(
        key=auth_service.SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
        max_age=max_age,
    )
    response.set_cookie(
        key=auth_service.CSRF_COOKIE_NAME,
        value=raw_csrf_token,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
        max_age=max_age,
    )


def _clear_session_cookies(response: Response, *, settings: Settings) -> None:
    for name in (auth_service.SESSION_COOKIE_NAME, auth_service.CSRF_COOKIE_NAME):
        response.delete_cookie(key=name, path="/", secure=settings.session_cookie_secure, samesite="lax")


@router.post("/register", status_code=201, response_model=UserPublic)
def register(
    body: RegisterRequest,
    request: Request,
    conn: Annotated[Connection, Depends(get_db)],
    notification_provider: Annotated[
        NotificationProvider, Depends(get_auth_notification_provider)
    ],
) -> UserPublic:
    settings = _settings()
    auth_hardening.enforce_rate_limit(
        request,
        scope="register",
        identity=body.email,
        limit=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
        settings=settings,
    )
    user_id = auth_service.register_user(
        conn,
        email=body.email,
        password=body.password,
        first_name=body.first_name,
        last_name=body.last_name,
    )
    row = users_repo.get_user_by_id(conn, user_id)
    raw_token = auth_hardening.issue_action_token(
        conn,
        user_id=user_id,
        purpose=auth_hardening.EMAIL_VERIFICATION,
        ttl_seconds=settings.email_verification_token_ttl_seconds,
    )
    link = f"{settings.frontend_base_url.rstrip('/')}/verify-email?token={raw_token}"
    try:
        notification_provider.send_email_verification(
            to_email=row["email_normalized"], verification_link=link
        )
    except NotificationDeliveryError:
        pass
    return _user_public(row)


@router.post("/login", response_model=UserPublic)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    conn: Annotated[Connection, Depends(get_db)],
) -> UserPublic:
    settings = _settings()
    auth_hardening.enforce_rate_limit(
        request,
        scope="login",
        identity=body.email,
        limit=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
        settings=settings,
    )
    candidate = users_repo.get_user_by_email(
        conn, auth_service.normalize_email(body.email)
    )
    if candidate is not None and auth_hardening.is_account_locked(candidate):
        # Preserve expensive password verification and generic response so
        # lock state cannot be used as an account-enumeration oracle.
        auth_service.verify_password(candidate["password_hash"], body.password)
        raise ApiError(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message="E-posta veya parola hatalı.",
        )
    try:
        row = auth_service.authenticate_user(conn, email=body.email, password=body.password)
    except ApiError:
        if candidate is not None:
            auth_hardening.record_login_failure(
                conn,
                candidate,
                settings=settings,
                request_id=getattr(request.state, "request_id", None),
            )
            # Authentication intentionally returns an error, but the abuse
            # counter/audit mutation must survive the request dependency's
            # error rollback. Both records commit atomically here.
            conn.commit()
        raise
    auth_hardening.clear_login_failures(conn, user_id=row["id"])
    if settings.email_verification_required and row["email_verified_at"] is None:
        raise ApiError(
            status_code=403,
            code="EMAIL_VERIFICATION_REQUIRED",
            message="E-posta doğrulaması gerekli.",
        )
    issued = auth_service.create_session(conn, user_id=row["id"], settings=settings)
    _set_session_cookies(
        response,
        raw_token=issued.raw_token,
        raw_csrf_token=issued.raw_csrf_token,
        settings=settings,
    )
    return _user_public(row)


@router.post("/password-reset/request", status_code=202)
def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    conn: Annotated[Connection, Depends(get_db)],
    notification_provider: Annotated[
        NotificationProvider, Depends(get_auth_notification_provider)
    ],
) -> dict:
    settings = _settings()
    auth_hardening.enforce_rate_limit(
        request,
        scope="auth_reset",
        identity=body.email,
        limit=max(2, settings.login_rate_limit_attempts),
        window_seconds=settings.login_rate_limit_window_seconds,
        settings=settings,
    )
    row = users_repo.get_user_by_email(conn, auth_service.normalize_email(body.email))
    if row is not None and row["status"] == "active":
        raw_token = auth_hardening.issue_action_token(
            conn,
            user_id=row["id"],
            purpose=auth_hardening.PASSWORD_RESET,
            ttl_seconds=settings.password_reset_token_ttl_seconds,
        )
        link = f"{settings.frontend_base_url.rstrip('/')}/reset-password?token={raw_token}"
        try:
            notification_provider.send_password_reset(
                to_email=row["email_normalized"], reset_link=link
            )
        except NotificationDeliveryError:
            pass
    # Unknown/disabled accounts return the same body and status.
    return {"accepted": True}


@router.post("/password-reset/confirm")
def confirm_password_reset(
    body: PasswordResetConfirm,
    conn: Annotated[Connection, Depends(get_db)],
) -> dict:
    auth_hardening.complete_password_reset(
        conn, raw_token=body.token, new_password=body.new_password
    )
    return {"reset": True}


@router.post("/email-verification/request", status_code=202)
def request_email_verification(
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Annotated[Connection, Depends(get_db)],
    _csrf: Annotated[None, Depends(auth_service.require_csrf_protection)],
    notification_provider: Annotated[
        NotificationProvider, Depends(get_auth_notification_provider)
    ],
) -> dict:
    row = users_repo.get_user_by_id(conn, actor.user_id)
    if row is not None and row["email_verified_at"] is None:
        settings = _settings()
        raw_token = auth_hardening.issue_action_token(
            conn,
            user_id=row["id"],
            purpose=auth_hardening.EMAIL_VERIFICATION,
            ttl_seconds=settings.email_verification_token_ttl_seconds,
        )
        link = f"{settings.frontend_base_url.rstrip('/')}/verify-email?token={raw_token}"
        try:
            notification_provider.send_email_verification(
                to_email=row["email_normalized"], verification_link=link
            )
        except NotificationDeliveryError:
            pass
    return {"accepted": True}


@router.post("/email-verification/confirm")
def confirm_email_verification(
    body: EmailVerificationConfirm,
    conn: Annotated[Connection, Depends(get_db)],
) -> dict:
    auth_hardening.complete_email_verification(conn, raw_token=body.token)
    return {"verified": True}


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Annotated[Connection, Depends(get_db)],
    _csrf: Annotated[None, Depends(auth_service.require_csrf_protection)],
) -> None:
    settings = _settings()
    raw_token = auth_service.raw_session_token_from_request(
        request, cookie_name=auth_service.SESSION_COOKIE_NAME
    )
    if raw_token is not None:
        auth_service.revoke_session_by_token(conn, raw_token=raw_token)
    _clear_session_cookies(response, settings=settings)


@router.get("/me", response_model=UserPublic)
def me(
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    conn: Annotated[Connection, Depends(get_db)],
) -> UserPublic:
    row = users_repo.get_user_by_id(conn, actor.user_id)
    return _user_public(row)


@router.post("/sessions/revoke")
def revoke_sessions(
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    response: Response,
    conn: Annotated[Connection, Depends(get_db)],
    _csrf: Annotated[None, Depends(auth_service.require_csrf_protection)],
) -> dict:
    settings = _settings()
    revoked_count = auth_service.revoke_all_sessions(conn, user_id=actor.user_id)
    _clear_session_cookies(response, settings=settings)
    return {"revoked": revoked_count}
