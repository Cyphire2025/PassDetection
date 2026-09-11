"""httpOnly authentication cookie helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import Response

from app.core.config.settings import get_settings
from app.presentation.security.access_level import clear_access_level_cookie
from app.presentation.security.email_oauth_binding import clear_oauth_browser_bindings

ATTENDANCE_RUNTIME_COOKIE_NAME = "attendance_runtime"
ATTENDANCE_RUNTIME_COOKIE_PATH = "/api/v1/tour-operations/coordinator"


def set_access_cookie(
    response: Response, *, access_token: str, expires_at: datetime | None = None
) -> None:
    root_settings = get_settings()
    settings = root_settings.jwt
    secure = settings.cookie_secure or root_settings.is_production
    now = datetime.now(tz=UTC)
    deadline = expires_at or now + timedelta(minutes=settings.access_token_expire_minutes)
    response.set_cookie(
        settings.access_cookie_name,
        access_token,
        max_age=max(0, int((deadline - now).total_seconds())),
        expires=deadline,
        httponly=True,
        secure=secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    access_token_expires_at: datetime | None = None,
    refresh_token_expires_at: datetime | None = None,
) -> None:
    root_settings = get_settings()
    settings = root_settings.jwt
    secure = settings.cookie_secure or root_settings.is_production
    set_access_cookie(response, access_token=access_token, expires_at=access_token_expires_at)
    now = datetime.now(tz=UTC)
    deadline = refresh_token_expires_at or now + timedelta(days=settings.refresh_token_expire_days)
    response.set_cookie(
        settings.refresh_cookie_name,
        refresh_token,
        max_age=max(0, int((deadline - now).total_seconds())),
        expires=deadline,
        httponly=True,
        secure=secure,
        samesite=settings.cookie_samesite,
        path="/api/v1/auth",
    )


def clear_auth_cookies(response: Response) -> None:
    root_settings = get_settings()
    clear_oauth_browser_bindings(response, root_settings)
    clear_access_level_cookie(response)
    settings = root_settings.jwt
    secure = settings.cookie_secure or root_settings.is_production
    for name, path in (
        (settings.access_cookie_name, "/"),
        (settings.refresh_cookie_name, "/api/v1/auth"),
        (ATTENDANCE_RUNTIME_COOKIE_NAME, ATTENDANCE_RUNTIME_COOKIE_PATH),
    ):
        response.delete_cookie(
            name,
            path=path,
            secure=secure,
            samesite=(
                "strict" if name == ATTENDANCE_RUNTIME_COOKIE_NAME else settings.cookie_samesite
            ),
            httponly=True,
        )
