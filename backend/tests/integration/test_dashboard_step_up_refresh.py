"""A browser bootstrap refresh must preserve a verified, bounded step-up."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, Response
from sqlalchemy import select

from app.core.security.identity_security import (
    decrypt_mfa_secret,
    encrypt_mfa_secret,
    generate_mfa_secret,
    totp_code,
)
from app.core.security.jwt import decode_access_token
from app.infrastructure.database.models import (
    AuditLogModel,
    DashboardSessionModel,
    RefreshTokenModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.dashboard_step_up_repository import lock_step_up_session
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import auth_identity
from app.presentation.api.v1.schemas.auth_schemas import MFAStepUpRequest
from app.presentation.dependencies.auth import require_recent_mfa
from tests.integration.test_dashboard_weekly_session import (
    _browser,
    _stored,
    _utc,
    _verified_login,
)
from tests.integration.test_dashboard_weekly_session import (
    weekly_app as weekly_app,
)
from tests.integration.test_dashboard_weekly_session import (
    weekly_clock as weekly_clock,
)
from tests.unit.presentation.test_identity_step_up import (
    _session_request,
    _staff_with_mfa,
    _StepUpLimiter,
)


@pytest.mark.parametrize("method", ["totp", "recovery_code"])
async def test_http_step_up_survives_bootstrap_rotation_but_not_mfa_ttl(
    weekly_app, db_session, weekly_clock, monkeypatch, method,
):
    @weekly_app.post("/test/recent-mfa", dependencies=[Depends(require_recent_mfa)])
    async def sensitive_action():
        return {"authorized": True}
    # The application ends with an OAuth metadata mount at '/'.
    weekly_app.router.routes.insert(0, weekly_app.router.routes.pop())

    monkeypatch.setattr(auth_identity, "MFAStepUpRateLimiter", _StepUpLimiter)
    original_mfa = weekly_clock.now
    deadline = original_mfa + timedelta(days=7)
    user_id, token, login = await _verified_login(weekly_app, db_session, weekly_clock)
    original = await _stored(db_session, token)
    sid, version = original.session_id, original.session_version
    other = await RefreshTokenRepository(db_session).save(
        token="other-session-opaque", user_id=user_id, expires_at=deadline,
        session_version=version, authentication_methods=("pwd", "totp"),
        mfa_authenticated_at=original_mfa,
    )
    weekly_clock.now += timedelta(minutes=20)
    stepped_at = weekly_clock.now
    state = await db_session.get(UserSecurityStateModel, user_id)
    code = (totp_code(decrypt_mfa_secret(state.mfa_secret_ciphertext),
                     counter=int(stepped_at.timestamp()) // 30)
            if method == "totp" else login.json()["recovery_codes"][0])
    async with _browser(weekly_app, token) as browser:
        assert (await browser.post("/api/v1/auth/refresh")).status_code == 200
        assert (await browser.post("/test/recent-mfa")).status_code == 403
        current_token = browser.cookies.get("refresh_token")
        stepped = await browser.post("/api/v1/auth/mfa/step-up", json={"code": code})
        assert stepped.status_code == 200
        assert browser.cookies.get("refresh_token") == current_token
        assert (await browser.post("/test/recent-mfa")).status_code == 200
        for _ in range(2):
            assert (await browser.post("/api/v1/auth/refresh")).status_code == 200
            claims = decode_access_token(browser.cookies.get("access_token"))
            assert (claims["sid"], claims["sv"]) == (str(sid), version)
            assert claims["session_exp"] == int(deadline.timestamp())
            assert claims["mfa_at"] == int(stepped_at.timestamp())
            assert claims["amr"] == ["pwd", method]
            assert (await browser.post("/test/recent-mfa")).status_code == 200
        # An ordinary refresh at the boundary cannot renew the factor window.
        weekly_clock.now = stepped_at + timedelta(seconds=601)
        assert (await browser.post("/api/v1/auth/refresh")).status_code == 200
        assert (await browser.post("/test/recent-mfa")).status_code == 403
        assert (await browser.post("/api/v1/auth/mfa/step-up", json={"code": code})).status_code == 401
        current = await _stored(db_session, browser.cookies.get("refresh_token"))
        assert _utc(current.expires_at) == deadline
        assert _utc(current.mfa_authenticated_at) == stepped_at
        weekly_clock.now = deadline
        assert (await browser.post("/api/v1/auth/refresh")).status_code == 401
    await db_session.refresh(original)
    await db_session.refresh(other)
    assert original.is_revoked and _utc(original.mfa_authenticated_at) == original_mfa
    assert not other.is_revoked and _utc(other.mfa_authenticated_at) == original_mfa
    family = await db_session.get(DashboardSessionModel, sid)
    assert _utc(family.expires_at) == deadline


async def test_failed_commit_cannot_publish_assurance_cookie_or_consume_factor(db_session, monkeypatch):
    secret = generate_mfa_secret()
    user, state = await _staff_with_mfa(db_session, ciphertext=encrypt_mfa_secret(secret))
    request = await _session_request(db_session, user)
    current_user = await UserRepository(db_session).get_by_id(user.id)
    await db_session.commit()
    user_id = user.id
    monkeypatch.setattr(auth_identity, "MFAStepUpRateLimiter", _StepUpLimiter)
    response = Response()
    monkeypatch.setattr(db_session, "commit", AsyncMock(side_effect=RuntimeError("synthetic commit failure")))
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        await auth_identity.step_up_dashboard_session(
            body=MFAStepUpRequest(code=totp_code(secret, counter=int(datetime.now(UTC).timestamp()) // 30)),
            request=request, response=response, current_user=current_user, session=db_session,
        )
    assert not response.headers.getlist("set-cookie")
    await db_session.rollback()
    await db_session.refresh(state)
    assert state.mfa_last_counter is None
    assert not await db_session.scalar(select(AuditLogModel.id).where(
        AuditLogModel.user_id == user_id, AuditLogModel.action == "auth.step_up_completed"))
    credential = await db_session.scalar(select(RefreshTokenModel).where(RefreshTokenModel.user_id == user_id))
    assert _utc(credential.mfa_authenticated_at) < datetime.now(UTC) - timedelta(minutes=30)


@pytest.mark.parametrize("expired", [False, True])
async def test_step_up_cannot_extend_a_legacy_sliding_mfa_deadline(db_session, expired):
    now = datetime.now(UTC)
    secret = generate_mfa_secret()
    user, _ = await _staff_with_mfa(db_session, ciphertext=encrypt_mfa_secret(secret))
    original_mfa = now - timedelta(days=8 if expired else 6)
    original_deadline = original_mfa + timedelta(days=7)
    credential = await RefreshTokenRepository(db_session).save(
        token="legacy-sliding-step-up", user_id=user.id, expires_at=now + timedelta(days=7),
        session_version=2, authentication_methods=("pwd", "totp"),
        mfa_authenticated_at=original_mfa,
    )
    from app.domain.exceptions.exceptions import AuthenticationError
    kwargs = dict(user_id=user.id, session_id=credential.session_id,
                  session_version=2, deadline=credential.expires_at, now=now)
    if expired:
        with pytest.raises(AuthenticationError):
            await lock_step_up_session(db_session, **kwargs)
        assert _utc(credential.mfa_authenticated_at) == original_mfa
    else:
        locked = await lock_step_up_session(db_session, **kwargs)
        locked.record_assurance(method="totp", now=now)
        await db_session.flush()
        assert credential.mfa_authenticated_at == now
        assert credential.expires_at == original_deadline
        assert locked.family.expires_at == original_deadline


@pytest.mark.parametrize("boundary", ["deleted_account", "expiry_during_locks"])
async def test_step_up_rechecks_authority_and_expiry_after_locks(db_session, monkeypatch, boundary):
    from app.domain.exceptions.exceptions import AuthenticationError
    from app.infrastructure.repositories import dashboard_step_up_repository

    now = datetime.now(UTC)
    user, _ = await _staff_with_mfa(db_session, ciphertext=encrypt_mfa_secret(generate_mfa_secret()))
    credential = await RefreshTokenRepository(db_session).save(
        token="boundary-step-up", user_id=user.id, expires_at=now + timedelta(seconds=1),
        session_version=2, authentication_methods=("pwd", "totp"), mfa_authenticated_at=now,
    )
    if boundary == "deleted_account":
        user.deleted_at = now
        await db_session.flush()
    else:
        times = iter([now, now + timedelta(seconds=2)])

        class LockClock:
            @staticmethod
            def now(_tz):
                return next(times)

        monkeypatch.setattr(dashboard_step_up_repository, "datetime", LockClock)
    with pytest.raises(AuthenticationError):
        await lock_step_up_session(
            db_session, user_id=user.id, session_id=credential.session_id,
            session_version=2, deadline=credential.expires_at,
        )
    assert _utc(credential.mfa_authenticated_at) == now
