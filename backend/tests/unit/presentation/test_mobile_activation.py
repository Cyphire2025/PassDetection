from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.security.mobile_jwt import MobileAccessClaims
from app.presentation.api.v1.routes.mobile_auth import (
    activate_client_manager,
    change_mobile_password,
    router,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileActivationRequest,
    MobileDeviceInput,
    MobilePasswordChangeRequest,
)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/mobile/auth/activate",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


@pytest.mark.asyncio
async def test_invalid_and_expired_activation_tokens_share_generic_failure() -> None:
    limiter = MagicMock()
    limiter.check_allowed = AsyncMock()
    limiter.record_failure = AsyncMock()
    result = MagicMock()
    result.first.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    body = MobileActivationRequest(
        activation_token="x" * 32,
        new_password="StrongPassword!2026",
        device=MobileDeviceInput(
            installation_id="installation-0001",
            platform="android",
            app_version="1.0.0",
        ),
    )

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth._require_mobile_enabled"
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.LoginAttemptLimiter",
            return_value=limiter,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.hash_password",
            return_value="hashed-password",
        ),
    ):
        with pytest.raises(HTTPException) as caught:
            await activate_client_manager(body, _request(), session)

    assert caught.value.status_code == 401
    assert caught.value.detail == "Activation link is invalid or expired"
    limiter.record_failure.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "client_manager_profiles.invitation_token_hash" in sql
    assert "client_manager_profiles.invitation_expires_at" in sql
    assert "client_manager_profiles.status = 'invited'" in sql
    assert "users.role = 'client_manager'" in sql
    assert "users.is_active IS true" in sql


def test_activation_route_is_registered_under_mobile_auth_router() -> None:
    route = next(item for item in router.routes if item.path == "/activate")
    assert route.methods == {"POST"}


@pytest.mark.asyncio
async def test_client_manager_password_change_revokes_old_family_and_clears_invitation() -> None:
    agency_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    user = SimpleNamespace(
        id=user_id,
        agency_id=agency_id,
        full_name="Client Manager",
        hashed_password="old-hash",
        updated_at=now,
    )
    old_session = SimpleNamespace(id=session_id)
    profile = SimpleNamespace(
        force_password_change=True,
        status="active",
        activated_at=now,
        suspended_at=None,
        invitation_token_hash="superseded-invitation-hash",
        invitation_expires_at=now + timedelta(days=1),
        access_generation=4,
        revision=8,
        updated_at=now,
    )
    user_session_result = MagicMock()
    user_session_result.first.return_value = (user, old_session)
    profile_result = MagicMock()
    profile_result.scalar_one.return_value = profile
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[user_session_result, profile_result])
    session.flush = AsyncMock()
    replacement = SimpleNamespace(access_token="new-access", refresh_token="new-refresh")
    revoke_family = AsyncMock()
    issue_session = AsyncMock(return_value=replacement)
    audit = AsyncMock()
    claims = MobileAccessClaims(
        principal_id=user_id,
        account_id=user_id,
        principal_type="client_manager",
        agency_id=agency_id,
        session_id=session_id,
        session_generation=3,
        password_change_required=False,
        expires_at=now + timedelta(minutes=15),
    )
    body = MobilePasswordChangeRequest(
        current_password="ExistingPass1",
        new_password="ReplacementPass2",
        device=MobileDeviceInput(
            installation_id="installation-0001",
            platform="android",
            app_version="1.0.0",
        ),
    )

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth.verify_password",
            return_value=True,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.hash_password",
            return_value="new-hash",
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._revoke_session_family",
            new=revoke_family,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._issue_user_session",
            new=issue_session,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._audit_mobile_auth",
            new=audit,
        ),
    ):
        result = await change_mobile_password(body, _request(), claims, session)

    assert result is replacement
    assert user.hashed_password == "new-hash"
    assert profile.invitation_token_hash is None
    assert profile.invitation_expires_at is None
    assert profile.access_generation == 5
    assert profile.revision == 9
    revoke_family.assert_awaited_once()
    assert revoke_family.await_args.args[:2] == (session, old_session)
    assert revoke_family.await_args.kwargs["reason"] == "password_changed"
    issue_session.assert_awaited_once_with(
        session,
        user=user,
        principal_type="client_manager",
        device=body.device,
        request=ANY,
        password_change_required=False,
    )
    audit.assert_awaited_once()
