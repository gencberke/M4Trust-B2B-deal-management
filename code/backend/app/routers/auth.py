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
from backend.app.schemas.identity import LoginRequest, RegisterRequest, UserPublic
from backend.app.services import auth as auth_service
from backend.app.services.access_control import ActorContext, require_authenticated_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
    conn: Annotated[Connection, Depends(get_db)],
) -> UserPublic:
    user_id = auth_service.register_user(
        conn,
        email=body.email,
        password=body.password,
        first_name=body.first_name,
        last_name=body.last_name,
    )
    row = users_repo.get_user_by_id(conn, user_id)
    return _user_public(row)


@router.post("/login", response_model=UserPublic)
def login(
    body: LoginRequest,
    response: Response,
    conn: Annotated[Connection, Depends(get_db)],
) -> UserPublic:
    settings = _settings()
    row = auth_service.authenticate_user(conn, email=body.email, password=body.password)
    issued = auth_service.create_session(conn, user_id=row["id"], settings=settings)
    _set_session_cookies(
        response,
        raw_token=issued.raw_token,
        raw_csrf_token=issued.raw_csrf_token,
        settings=settings,
    )
    return _user_public(row)


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
