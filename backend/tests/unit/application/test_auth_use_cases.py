"""
Tests: Auth Use Cases
=====================
Unit tests for LoginUseCase, RefreshTokenUseCase, LogoutUseCase.
Uses unittest.mock — no real DB required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.application.dtos.auth_dtos import LoginInputDTO, RefreshTokenInputDTO
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.application.use_cases.auth.logout_use_case import LogoutUseCase
from app.application.use_cases.auth.refresh_token_use_case import RefreshTokenUseCase
from app.core.security.password import hash_password
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthenticationError, TokenExpiredError


def _make_user(is_active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email="test@agency.com",
        hashed_password=hash_password("SecurePass1!"),
        full_name="Test User",
        role=UserRole.AGENCY_STAFF,
        agency_id=None,
        is_active=is_active,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )


class TestLoginUseCase:
    def _make_use_case(self, user: User | None = None):
        user_repo  = AsyncMock()
        token_repo = AsyncMock()
        login_limiter = AsyncMock()
        user_repo.get_by_email.return_value = user
        return LoginUseCase(user_repo, token_repo, login_limiter), user_repo, token_repo

    @pytest.mark.asyncio
    async def test_login_success(self) -> None:
        user = _make_user()
        use_case, user_repo, token_repo = self._make_use_case(user)

        result = await use_case.execute(
            LoginInputDTO(email="test@agency.com", password="SecurePass1!")
        )

        assert result.access_token
        assert result.refresh_token
        assert result.user.email == "test@agency.com"
        user_repo.update.assert_called_once()
        token_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_user_not_found(self) -> None:
        use_case, _, _ = self._make_use_case(user=None)
        with pytest.raises(AuthenticationError):
            await use_case.execute(
                LoginInputDTO(email="nobody@x.com", password="whatever")
            )

    @pytest.mark.asyncio
    async def test_login_wrong_password(self) -> None:
        user = _make_user()
        use_case, _, _ = self._make_use_case(user)
        with pytest.raises(AuthenticationError):
            await use_case.execute(
                LoginInputDTO(email="test@agency.com", password="WrongPassword1!")
            )

    @pytest.mark.asyncio
    async def test_login_inactive_user(self) -> None:
        user = _make_user(is_active=False)
        use_case, _, _ = self._make_use_case(user)
        with pytest.raises(AuthenticationError, match="deactivated"):
            await use_case.execute(
                LoginInputDTO(email="test@agency.com", password="SecurePass1!")
            )


class TestLogoutUseCase:
    @pytest.mark.asyncio
    async def test_logout_revokes_token(self) -> None:
        token_repo = AsyncMock()
        use_case   = LogoutUseCase(token_repo)

        await use_case.execute("some-refresh-token")

        token_repo.revoke.assert_called_once_with("some-refresh-token")


class TestRefreshTokenUseCase:
    @pytest.mark.asyncio
    async def test_refresh_raises_when_token_invalid(self) -> None:
        user_repo  = AsyncMock()
        token_repo = AsyncMock()
        token_repo.get_valid_token.return_value = None  # not found in DB

        use_case = RefreshTokenUseCase(user_repo, token_repo)

        with pytest.raises(TokenExpiredError):
            await use_case.execute(RefreshTokenInputDTO(refresh_token="bad-token"))
