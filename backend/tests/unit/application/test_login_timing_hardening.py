from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import bcrypt
import pytest

from app.application.dtos.auth_dtos import LoginInputDTO
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.domain.entities.entities import User, UserRole
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


@pytest.mark.asyncio
async def test_owned_login_limiter_is_lazy_and_deterministically_closed() -> None:
    users = AsyncMock()
    users.get_by_email.return_value = None
    tokens = AsyncMock()
    limiter = AsyncMock()

    with patch(
        "app.application.use_cases.auth.login_use_case.LoginAttemptLimiter",
        return_value=limiter,
    ) as limiter_factory:
        use_case = LoginUseCase(users, tokens)
        limiter_factory.assert_not_called()

        with (
            patch(
                "app.application.use_cases.auth.login_use_case.verify_password",
                return_value=False,
            ),
            pytest.raises(AuthenticationError, match="Invalid email or password"),
        ):
            await use_case.verify_credentials(
                LoginInputDTO(email="missing@example.com", password="attempted-password")
            )

        limiter_factory.assert_called_once_with()
        await use_case.aclose()
        await use_case.aclose()

    limiter.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_injected_login_limiter_remains_owned_by_its_caller() -> None:
    limiter = AsyncMock()
    use_case = LoginUseCase(AsyncMock(), AsyncMock(), limiter)

    await use_case.aclose()

    limiter.aclose.assert_not_awaited()


@pytest.mark.parametrize("password", ["Aa1" + "x" * 90, "Aa1" + "é" * 40])
async def test_retained_long_password_authenticates_through_real_login_boundary(password):
    user = User(id=uuid.uuid4(), email="legacy@example.test", full_name="Legacy fixture",
                hashed_password=bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt(rounds=4)).decode(),
                role=UserRole.AGENCY_STAFF, agency_id=uuid.uuid4(), credential_state="active")
    users = AsyncMock()
    users.get_by_email.return_value = user
    limiter = AsyncMock()
    use_case = LoginUseCase(users, AsyncMock(), limiter)
    assert await use_case.verify_credentials(LoginInputDTO(email=user.email, password=password)) is user
    with pytest.raises(AuthenticationError, match="Invalid email or password"):
        await use_case.verify_credentials(LoginInputDTO(email=user.email, password="WrongPrefix1" + password))
    limiter.record_success.assert_awaited_once()
    limiter.record_failure.assert_awaited_once()
