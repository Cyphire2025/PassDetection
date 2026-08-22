"""httpOnly authentication cookie helpers."""

from __future__ import annotations

from fastapi import Response

from app.core.config.settings import get_settings


def set_access_cookie(response: Response, *, access_token: str) -> None:
    root_settings = get_settings()
    settings = root_settings.jwt
    secure = settings.cookie_secure or root_settings.is_production
    response.set_cookie(
        settings.access_cookie_name,
        access_token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def set_auth_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    root_settings = get_settings()
    settings = root_settings.jwt
    secure = settings.cookie_secure or root_settings.is_production
    set_access_cookie(response, access_token=access_token)
    response.set_cookie(
        settings.refresh_cookie_name,
        refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite=settings.cookie_samesite,
        path="/api/v1/auth",
    )


def clear_auth_cookies(response: Response) -> None:
    root_settings = get_settings()
    settings = root_settings.jwt
    secure = settings.cookie_secure or root_settings.is_production
    for name, path in (
        (settings.access_cookie_name, "/"),
        (settings.refresh_cookie_name, "/api/v1/auth"),
    ):
        response.delete_cookie(
            name,
            path=path,
            secure=secure,
            samesite=settings.cookie_samesite,
            httponly=True,
        )
