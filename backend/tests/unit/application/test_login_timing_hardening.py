from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.application.dtos.auth_dtos import LoginInputDTO
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.domain.exceptions.exceptions import AuthenticationError


@pytest.mark.asyncio
async def test_unknown_user_runs_dummy_password_verification() -> None:
    users = AsyncMock()
    users.get_by_email.return_value = None
    tokens = AsyncMock()
    limiter = AsyncMock()
    use_case = LoginUseCase(users, tokens, limiter)

    with (
        patch(
            "app.application.use_cases.auth.login_use_case.verify_password",
            return_value=False,
        ) as verify,
        pytest.raises(AuthenticationError, match="Invalid email or password"),
    ):
        await use_case.execute(
            LoginInputDTO(email="missing@example.com", password="attempted-password")
        )

    verify.assert_called_once()
    assert verify.call_args.args[0] == "attempted-password"
    assert verify.call_args.args[1].startswith("$2b$12$")
    limiter.record_failure.assert_awaited_once()
