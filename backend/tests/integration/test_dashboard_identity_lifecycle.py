from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.identity_security import totp_code
from app.core.security.password import hash_password
from app.infrastructure.database.models import (
    IdentityActionTokenModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.security.login_attempt_limiter import LoginAttemptLimiter


@pytest.mark.asyncio
async def test_privileged_login_enrolls_mfa_before_session_and_fences_access_tokens(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_attempt(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(LoginAttemptLimiter, "check_allowed", allow_attempt)
    monkeypatch.setattr(LoginAttemptLimiter, "record_success", allow_attempt)
    monkeypatch.setattr(LoginAttemptLimiter, "record_failure", allow_attempt)
    user = UserModel(
        email="mfa-enrollment@example.test",
        hashed_password=hash_password("StrongPassword9"),
        full_name="MFA Enrollment User",
        role="agency_staff",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    security_state = UserSecurityStateModel(
        user_id=user.id,
        credential_state="active",
        session_version=1,
        mfa_required=True,
    )
    db_session.add(security_state)
    await db_session.flush()

    password_response = await client.post(
        "/api/v1/auth/login",
        data={"username": user.email, "password": "StrongPassword9"},
    )

    assert password_response.status_code == 200
    challenge = password_response.json()
    assert challenge["status"] == "mfa_enrollment_required"
    assert challenge["setup_secret"]
    assert not client.cookies.get("refresh_token")

    now = datetime.now(tz=UTC)
    counter = int(now.timestamp()) // 30
    verification_response = await client.post(
        "/api/v1/auth/mfa/verify",
        json={
            "challenge_token": challenge["challenge_token"],
            "code": totp_code(challenge["setup_secret"], counter=counter),
        },
    )

    assert verification_response.status_code == 200
    authenticated = verification_response.json()
    assert authenticated["status"] == "authenticated"
    assert authenticated["user"]["mfa_enabled"] is True
    assert len(authenticated["recovery_codes"]) == 10
    assert client.cookies.get("refresh_token")
    enrolled_access_token = client.cookies.get("access_token")
    assert enrolled_access_token

    replay_response = await client.post(
        "/api/v1/auth/mfa/verify",
        json={
            "challenge_token": challenge["challenge_token"],
            "code": totp_code(challenge["setup_secret"], counter=counter),
        },
    )
    assert replay_response.status_code == 401

    regenerated_response = await client.post(
        "/api/v1/auth/mfa/recovery-codes/regenerate",
        headers={"Authorization": f"Bearer {enrolled_access_token}"},
    )
    assert regenerated_response.status_code == 200
    assert len(regenerated_response.json()["recovery_codes"]) == 10
    rotated_access_token = client.cookies.get("access_token")
    assert rotated_access_token
    assert rotated_access_token != enrolled_access_token
    stale_factor_session = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {enrolled_access_token}"},
    )
    assert stale_factor_session.status_code == 401
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    security_state.session_version += 1
    await db_session.flush()
    stale_access_response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {rotated_access_token}"},
    )
    assert stale_access_response.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_recovery_neutrally_excludes_mobile_only_client_managers(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    client_manager = UserModel(
        email="mobile-only-manager@example.com",
        hashed_password=hash_password("ExistingPassword9"),
        full_name="Mobile Only Manager",
        role="client_manager",
        is_active=True,
    )
    db_session.add(client_manager)
    await db_session.flush()

    response = await client.post(
        "/api/v1/auth/password/recovery/request",
        json={"email": client_manager.email},
    )

    assert response.status_code == 202
    assert response.json()["development_recovery_token"] is None
    issued_tokens = (
        await db_session.execute(
            select(IdentityActionTokenModel).where(
                IdentityActionTokenModel.user_id == client_manager.id
            )
        )
    ).scalars().all()
    assert issued_tokens == []
