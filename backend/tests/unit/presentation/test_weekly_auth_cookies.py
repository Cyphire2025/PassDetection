from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie

import pytest
from fastapi import Response

from app.core.config.settings import JWTSettings, Settings
from app.presentation.security import auth_cookies

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def deterministic_cookie_settings(monkeypatch, test_settings: Settings) -> None:
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    settings = JWTSettings(
        access_token_expire_minutes=30,
        refresh_token_expire_days=7,
        cookie_secure=False,
        cookie_samesite="lax",
        _env_file=None,
    )
    monkeypatch.setattr(Settings, "jwt", property(lambda _self: settings))
    monkeypatch.setattr(auth_cookies, "get_settings", lambda: test_settings)
    monkeypatch.setattr(auth_cookies, "datetime", FrozenDatetime, raising=False)


def response_cookies(response: Response) -> SimpleCookie:
    cookies = SimpleCookie()
    for header in response.headers.getlist("set-cookie"):
        cookies.load(header)
    return cookies


def test_first_login_persists_refresh_cookie_for_seven_days(test_settings: Settings) -> None:
    response = Response()
    auth_cookies.set_auth_cookies(
        response, access_token="short-access", refresh_token="opaque-refresh"
    )
    cookies = response_cookies(response)
    access = cookies[test_settings.jwt.access_cookie_name]
    refresh = cookies[test_settings.jwt.refresh_cookie_name]

    assert access.value == "short-access"
    assert int(access["max-age"]) == 30 * 60
    assert parsedate_to_datetime(access["expires"]) == NOW + timedelta(minutes=30)
    assert access["path"] == "/"
    assert access["httponly"] is True
    assert refresh.value == "opaque-refresh"
    assert int(refresh["max-age"]) == 7 * 24 * 60 * 60
    assert parsedate_to_datetime(refresh["expires"]) == NOW + timedelta(days=7)
    assert refresh["path"] == "/api/v1/auth"
    assert refresh["httponly"] is True
    assert refresh["samesite"] == "lax"


def test_refresh_cookie_retains_one_remaining_day_instead_of_starting_another_week(
    test_settings: Settings,
) -> None:
    response = Response()
    access_deadline = NOW + timedelta(minutes=30)
    session_deadline = NOW + timedelta(days=1)
    auth_cookies.set_auth_cookies(
        response,
        access_token="replacement-access",
        refresh_token="replacement-refresh",
        access_token_expires_at=access_deadline,
        refresh_token_expires_at=session_deadline,
    )
    cookies = response_cookies(response)

    access = cookies[test_settings.jwt.access_cookie_name]
    refresh = cookies[test_settings.jwt.refresh_cookie_name]
    assert int(access["max-age"]) == 30 * 60
    assert parsedate_to_datetime(access["expires"]) == access_deadline
    assert int(refresh["max-age"]) == 24 * 60 * 60
    assert parsedate_to_datetime(refresh["expires"]) == session_deadline


def test_access_cookie_honors_token_expiration_at_session_boundary(
    test_settings: Settings,
) -> None:
    response = Response()
    deadline = NOW + timedelta(seconds=12)
    auth_cookies.set_access_cookie(response, access_token="last-access", expires_at=deadline)
    cookie = response_cookies(response)[test_settings.jwt.access_cookie_name]

    assert int(cookie["max-age"]) == 12
    assert parsedate_to_datetime(cookie["expires"]) == deadline


def test_production_session_cookies_are_secure_even_without_explicit_cookie_secure(
    monkeypatch,
    test_settings: Settings,
) -> None:
    production_settings = test_settings.model_copy(update={"app_env": "production"})
    monkeypatch.setattr(auth_cookies, "get_settings", lambda: production_settings)
    response = Response()
    auth_cookies.set_auth_cookies(
        response, access_token="short-access", refresh_token="opaque-refresh"
    )

    for cookie in response_cookies(response).values():
        assert cookie["secure"] is True
        assert cookie["httponly"] is True
        assert cookie["samesite"] == "lax"
