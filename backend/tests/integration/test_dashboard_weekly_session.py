from __future__ import annotations

import importlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings, get_settings
from app.core.security.identity_security import decrypt_mfa_secret, totp_code
from app.core.security.jwt import hash_refresh_token
from app.core.security.password import hash_password
from app.infrastructure.database.models import RefreshTokenModel, UserModel, UserSecurityStateModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.login_attempt_limiter import LoginAttemptLimiter
from app.main import create_application


@dataclass
class SessionClock:
    now: datetime


@pytest.fixture
def weekly_clock(monkeypatch: pytest.MonkeyPatch) -> SessionClock:
    clock = SessionClock(datetime.now(tz=UTC).replace(microsecond=0))

    class DateTimeMeta(type):
        def __instancecheck__(cls, instance: object) -> bool:
            # PyJWT also uses isinstance(datetime) when serializing DB deadlines.
            return isinstance(instance, datetime)

    class ControlledDateTime(datetime, metaclass=DateTimeMeta):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return clock.now.astimezone(tz) if tz else clock.now.replace(tzinfo=None)

    for module_name in (
        "app.core.security.jwt",
        "app.application.use_cases.auth.refresh_token_use_case",
        "app.infrastructure.repositories.refresh_token_repository",
        "app.infrastructure.repositories.identity_security_repository",
        "app.presentation.api.v1.routes.auth_identity",
        "app.presentation.dependencies.auth",
        "app.presentation.security.auth_cookies",
        "jwt.api_jwt",
    ):
        monkeypatch.setattr(importlib.import_module(module_name), "datetime", ControlledDateTime)
    monkeypatch.setattr(get_settings().jwt, "refresh_token_expire_days", 7)
    monkeypatch.setattr(get_settings().jwt, "access_token_expire_minutes", 30)
    monkeypatch.setattr(get_settings().jwt, "cookie_samesite", "lax")

    async def allow_attempt(*_args: object, **_kwargs: object) -> None:
        return None

    for method in ("check_allowed", "record_success", "record_failure"):
        monkeypatch.setattr(LoginAttemptLimiter, method, allow_attempt)
    return clock


@pytest.fixture
def weekly_app(db_session: AsyncSession, test_settings: Settings) -> FastAPI:
    app = create_application(settings=test_settings, initialize_rate_limit_redis=False)

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db
    return app


def _browser(app: FastAPI, refresh_token: str | None = None) -> AsyncClient:
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://testserver",
        headers={"Origin": get_settings().allowed_origins[0]},
    )
    if refresh_token is not None:
        # Reopening retains only the persistent HttpOnly refresh cookie.
        client.cookies.set("refresh_token", refresh_token, domain="testserver.local", path="/api/v1/auth")
    return client


async def _verified_login(
    app: FastAPI, session: AsyncSession, clock: SessionClock,
) -> tuple[uuid.UUID, str, Response]:
    user = UserModel(
        email="weekly-session@example.test",
        hashed_password=hash_password("StrongPassword9"),
        full_name="Weekly Session User",
        role="agency_staff",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(UserSecurityStateModel(
        user_id=user.id, credential_state="active", session_version=1, mfa_required=True,
    ))
    await session.flush()

    async with _browser(app) as browser:
        password = await browser.post(
            "/api/v1/auth/login",
            data={"username": user.email, "password": "StrongPassword9"},
        )
        assert password.status_code == 200
        challenge = password.json()
        assert challenge["status"] == "mfa_enrollment_required"
        assert browser.cookies.get("refresh_token") is None
        verified = await browser.post(
            "/api/v1/auth/mfa/verify",
            json={
                "challenge_token": challenge["challenge_token"],
                "code": totp_code(challenge["setup_secret"], counter=int(clock.now.timestamp()) // 30),
            },
        )
        assert verified.status_code == 200
        assert verified.json()["status"] == "authenticated"
        refresh_token = browser.cookies.get("refresh_token")
        assert refresh_token
        return user.id, refresh_token, verified


def _cookie(response: Response, name: str):
    cookies = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        cookies.load(header)
    return cookies[name]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _stored(session: AsyncSession, token: str) -> RefreshTokenModel:
    return (await session.execute(
        select(RefreshTokenModel)
        .where(RefreshTokenModel.token == hash_refresh_token(token))
        .execution_options(populate_existing=True),
    )).scalar_one()


@pytest.mark.asyncio
async def test_reopened_browser_restores_mfa_session_and_rotates_until_original_deadline(
    weekly_app: FastAPI, db_session: AsyncSession, weekly_clock: SessionClock,
) -> None:
    signed_in_at = weekly_clock.now
    deadline = signed_in_at + timedelta(days=7)
    user_id, token, login = await _verified_login(weekly_app, db_session, weekly_clock)
    cookie = _cookie(login, "refresh_token")
    assert cookie["httponly"]
    assert cookie["path"] == "/api/v1/auth"
    assert cookie["samesite"] == "lax"
    assert int(cookie["max-age"]) == 7 * 24 * 60 * 60
    assert parsedate_to_datetime(cookie["expires"]) == deadline

    for offset in (timedelta(hours=1), timedelta(days=6), timedelta(days=7, seconds=-60)):
        weekly_clock.now = signed_in_at + offset
        prior_token = token
        async with _browser(weekly_app, token) as reopened:
            assert reopened.cookies.get("access_token") is None
            response = await reopened.post("/api/v1/auth/refresh")
            assert "access_token=" not in response.request.headers.get("cookie", "")
            assert response.status_code == 200
            assert response.json()["status"] == "authenticated"
            assert response.json()["user"]["id"] == str(user_id)
            token = reopened.cookies.get("refresh_token")
            assert token and token != prior_token
            current_access = reopened.cookies.get("access_token")
            assert current_access
            claims = jwt.decode(current_access, options={"verify_signature": False})
            assert claims["session_exp"] == int(deadline.timestamp())
            assert claims["mfa_at"] == int(signed_in_at.timestamp())
            assert "totp" in claims["amr"]
            assert (await reopened.get("/api/v1/auth/me")).status_code == 200

        remaining = int((deadline - weekly_clock.now).total_seconds())
        rotated_cookie = _cookie(response, "refresh_token")
        assert int(rotated_cookie["max-age"]) == remaining
        assert parsedate_to_datetime(rotated_cookie["expires"]) == deadline
        assert int(_cookie(response, "access_token")["max-age"]) <= min(1800, remaining)
        assert (await _stored(db_session, prior_token)).is_revoked
        stored = await _stored(db_session, token)
        assert _utc(stored.expires_at) == deadline
        assert _utc(stored.mfa_authenticated_at) == signed_in_at


@pytest.mark.asyncio
async def test_refresh_at_seven_day_deadline_requires_a_new_verified_login(
    weekly_app: FastAPI, db_session: AsyncSession, weekly_clock: SessionClock,
) -> None:
    _, token, _ = await _verified_login(weekly_app, db_session, weekly_clock)
    weekly_clock.now += timedelta(days=7)
    async with _browser(weekly_app, token) as reopened:
        response = await reopened.post("/api/v1/auth/refresh")
        assert response.status_code == 401
        assert int(_cookie(response, "refresh_token")["max-age"]) == 0
        assert reopened.cookies.get("access_token") is None


@pytest.mark.asyncio
async def test_legacy_sliding_expiry_cannot_extend_past_original_mfa_login(
    weekly_app: FastAPI, db_session: AsyncSession, weekly_clock: SessionClock,
) -> None:
    _, token, _ = await _verified_login(weekly_app, db_session, weekly_clock)
    stored = await _stored(db_session, token)
    stored.expires_at = weekly_clock.now + timedelta(days=14)
    await db_session.flush()
    weekly_clock.now += timedelta(days=8)

    async with _browser(weekly_app, token) as reopened:
        response = await reopened.post("/api/v1/auth/refresh")
        assert response.status_code == 401
        assert int(_cookie(response, "refresh_token")["max-age"]) == 0
    await db_session.refresh(stored)
    assert stored.is_revoked


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["logout", "session_version"])
async def test_remembered_browser_session_remains_revocable_before_seven_days(
    weekly_app: FastAPI,
    db_session: AsyncSession,
    weekly_clock: SessionClock,
    revocation: str,
) -> None:
    user_id, token, _ = await _verified_login(weekly_app, db_session, weekly_clock)
    weekly_clock.now += timedelta(days=1)
    if revocation == "logout":
        async with _browser(weekly_app, token) as browser:
            assert (await browser.post("/api/v1/auth/logout")).status_code == 204
    else:
        state = (await db_session.execute(
            select(UserSecurityStateModel).where(UserSecurityStateModel.user_id == user_id),
        )).scalar_one()
        state.session_version += 1
        await db_session.flush()
    async with _browser(weekly_app, token) as reopened:
        response = await reopened.post("/api/v1/auth/refresh")
        assert response.status_code == 401
        assert int(_cookie(response, "refresh_token")["max-age"]) == 0


@pytest.mark.asyncio
async def test_step_up_and_recovery_code_rotation_preserve_original_login_deadline(
    weekly_app: FastAPI,
    db_session: AsyncSession,
    weekly_clock: SessionClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_step_up(*_args: object, **_kwargs: object) -> None:
        return None

    # Replace only external rate-limit I/O; factor verification and session
    # authorization still run through the actual application and database.
    limiter_type = type("LocalStepUpLimiter", (), {
        "ensure_available": allow_step_up,
        "record_failure": allow_step_up,
        "clear": allow_step_up,
        "close": allow_step_up,
    })
    monkeypatch.setattr(
        importlib.import_module("app.presentation.api.v1.routes.auth_identity"),
        "MFAStepUpRateLimiter", limiter_type,
    )
    signed_in_at = weekly_clock.now
    deadline = signed_in_at + timedelta(days=7)
    user_id, token, _ = await _verified_login(weekly_app, db_session, weekly_clock)
    state = (await db_session.execute(
        select(UserSecurityStateModel).where(UserSecurityStateModel.user_id == user_id),
    )).scalar_one()
    original_version = state.session_version
    assert state.mfa_secret_ciphertext
    secret = decrypt_mfa_secret(state.mfa_secret_ciphertext)
    weekly_clock.now += timedelta(days=6)

    async with _browser(weekly_app, token) as reopened:
        assert (await reopened.post("/api/v1/auth/refresh")).status_code == 200
        prior_token = reopened.cookies.get("refresh_token")
        assert prior_token
        requires_step_up = await reopened.post("/api/v1/auth/mfa/recovery-codes/regenerate")
        assert requires_step_up.status_code == 403

        stepped_up = await reopened.post("/api/v1/auth/mfa/step-up", json={
            "code": totp_code(secret, counter=int(weekly_clock.now.timestamp()) // 30),
        })
        assert stepped_up.status_code == 200
        assert reopened.cookies.get("refresh_token") == prior_token
        stepped_up_access = reopened.cookies.get("access_token")
        assert stepped_up_access
        stepped_up_claims = jwt.decode(stepped_up_access, options={"verify_signature": False})
        assert stepped_up_claims["mfa_at"] == int(weekly_clock.now.timestamp())
        assert stepped_up_claims["session_exp"] == int(deadline.timestamp())

        regenerated = await reopened.post("/api/v1/auth/mfa/recovery-codes/regenerate")
        assert regenerated.status_code == 200
        assert len(regenerated.json()["recovery_codes"]) == 10
        replacement_token = reopened.cookies.get("refresh_token")
        assert replacement_token and replacement_token != prior_token
        assert int(_cookie(regenerated, "refresh_token")["max-age"]) == 24 * 60 * 60
        assert parsedate_to_datetime(_cookie(regenerated, "refresh_token")["expires"]) == deadline
        await db_session.refresh(state)
        assert state.session_version == original_version + 1
        assert (await _stored(db_session, prior_token)).is_revoked
        assert _utc((await _stored(db_session, replacement_token)).expires_at) == deadline
        assert (await reopened.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {stepped_up_access}"},
        )).status_code == 401
        assert (await reopened.get("/api/v1/auth/me")).status_code == 200

    weekly_clock.now = deadline
    async with _browser(weekly_app, replacement_token) as reopened:
        assert (await reopened.post("/api/v1/auth/refresh")).status_code == 401
