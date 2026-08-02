from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.presentation.api.v1.routes.mobile_auth import activate_client_manager, router
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileActivationRequest,
    MobileDeviceInput,
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
