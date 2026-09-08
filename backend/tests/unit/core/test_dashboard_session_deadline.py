from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config.settings import JWTSettings, Settings
from app.core.security import jwt as dashboard_jwt
from app.domain.exceptions.exceptions import AuthenticationError, TokenExpiredError

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def deterministic_session_settings(monkeypatch, test_settings: Settings) -> None:
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    settings = JWTSettings(
        access_token_expire_minutes=30,
        refresh_token_expire_days=7,
        _env_file=None,
    )
    monkeypatch.setattr(Settings, "jwt", property(lambda _self: settings))
    monkeypatch.setattr(dashboard_jwt, "_settings", test_settings)
    monkeypatch.setattr(dashboard_jwt, "datetime", FrozenDatetime)


def decoded_payload(token: str, settings: Settings) -> dict:
    # Verify the real signature, while token timestamps use the injected clock.
    return jwt.decode(
        token,
        settings.app_secret_key,
        algorithms=[settings.jwt.algorithm],
        options={"verify_exp": False, "verify_iat": False},
    )


def test_first_login_refresh_token_has_a_seven_day_absolute_deadline() -> None:
    token, expires_at = dashboard_jwt.create_refresh_token()

    assert expires_at == NOW + timedelta(days=7)
    assert str(uuid.UUID(token)) == token


def test_access_token_stays_short_lived_inside_the_verified_week(
    test_settings: Settings,
) -> None:
    deadline = NOW + timedelta(days=7)
    user_id = uuid.uuid4()
    token, expires_at = dashboard_jwt.create_access_token(
        user_id,
        "super_admin",
        authentication_methods=("pwd", "totp"),
        mfa_authenticated_at=NOW,
        session_expires_at=deadline,
    )
    payload = decoded_payload(token, test_settings)

    assert expires_at == NOW + timedelta(minutes=30)
    assert payload["exp"] == int(expires_at.timestamp())
    assert payload["session_exp"] == int(deadline.timestamp())
    assert payload["sub"] == str(user_id)
    assert payload["amr"] == ["pwd", "totp"]
    assert payload["mfa_at"] == int(NOW.timestamp())


def test_rotating_refresh_token_preserves_the_original_deadline() -> None:
    original_deadline = NOW + timedelta(days=1)

    first_token, first_expiry = dashboard_jwt.create_refresh_token(expires_at=original_deadline)
    replacement_token, replacement_expiry = dashboard_jwt.create_refresh_token(
        expires_at=first_expiry
    )

    assert replacement_token != first_token
    assert replacement_expiry == first_expiry == original_deadline
    assert replacement_expiry != NOW + timedelta(days=7)


def test_access_token_cannot_outlive_the_last_seconds_of_the_session(
    test_settings: Settings,
) -> None:
    deadline = NOW + timedelta(seconds=12)
    token, expires_at = dashboard_jwt.create_access_token(
        uuid.uuid4(), "agency_staff", session_expires_at=deadline
    )
    payload = decoded_payload(token, test_settings)

    assert expires_at == deadline
    assert payload["exp"] == payload["session_exp"] == int(deadline.timestamp())


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(seconds=-1)])
def test_expired_session_cannot_issue_an_access_token(offset: timedelta) -> None:
    with pytest.raises(TokenExpiredError):
        dashboard_jwt.create_access_token(
            uuid.uuid4(), "agency_staff", session_expires_at=NOW + offset
        )


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(seconds=-1)])
def test_expired_session_cannot_issue_a_replacement_refresh_token(offset: timedelta) -> None:
    with pytest.raises(TokenExpiredError):
        dashboard_jwt.create_refresh_token(expires_at=NOW + offset)


def test_opaque_weekly_refresh_token_is_not_an_access_token() -> None:
    token, _ = dashboard_jwt.create_refresh_token()

    assert len(dashboard_jwt.hash_refresh_token(token)) == 64
    assert dashboard_jwt.hash_refresh_token(token) != token
    with pytest.raises(AuthenticationError):
        dashboard_jwt.decode_access_token(token)
