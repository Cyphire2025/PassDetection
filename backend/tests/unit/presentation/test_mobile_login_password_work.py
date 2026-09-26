from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException, Request

from app.presentation.api.v1.routes.mobile_auth import mobile_credential_login


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "inactive", "no_agency", "wrong_password"])
async def test_mobile_failed_credentials_always_run_one_verifier(failure):
    user = None if failure == "missing" else SimpleNamespace(
        is_active=failure != "inactive", agency_id=None if failure == "no_agency" else "agency",
        hashed_password="synthetic-stored-hash",
    )
    session, limiter = AsyncMock(), AsyncMock()
    session.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=user))
    body = SimpleNamespace(email="unknown@example.test", password="WrongPassword1!")
    request = Request({"type": "http", "method": "POST", "headers": [], "client": ("192.0.2.1", 123)})
    with (
        patch("app.presentation.api.v1.routes.mobile_auth._require_mobile_enabled"),
        patch("app.presentation.api.v1.routes.mobile_auth.LoginAttemptLimiter", return_value=limiter),
        patch("app.presentation.api.v1.routes.mobile_auth.verify_password", return_value=False) as verifier,
        pytest.raises(HTTPException) as error,
    ):
        await mobile_credential_login(body, request, session)
    assert error.value.status_code == 401
    assert error.value.detail == "Invalid email or password"
    verifier.assert_called_once()
    assert verifier.call_args.args[0] == body.password
    limiter.record_failure.assert_awaited_once()
    limiter.aclose.assert_awaited_once()
