from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.application.dtos.auth_dtos import RefreshTokenInputDTO
from app.application.use_cases.auth.refresh_token_use_case import RefreshTokenUseCase
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import TokenExpiredError


def _user() -> User:
    now = datetime.now(tz=UTC)
    return User(
        id=uuid.uuid4(),
        email="refresh@example.com",
        hashed_password="unused",
        full_name="Refresh User",
        role=UserRole.AGENCY_STAFF,
        agency_id=uuid.uuid4(),
        is_active=True,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_refresh_atomically_consumes_token_before_issuing_successor() -> None:
    user = _user()
    stored_token = SimpleNamespace(user_id=user.id)
    user_repository = AsyncMock()
    user_repository.get_by_id.return_value = user
    token_repository = AsyncMock()
    token_repository.get_valid_token.return_value = stored_token
    token_repository.consume_valid_token.return_value = stored_token
    use_case = RefreshTokenUseCase(user_repository, token_repository)
    expires_at = datetime.now(tz=UTC) + timedelta(minutes=30)
    refresh_expires_at = datetime.now(tz=UTC) + timedelta(days=7)

    with (
        patch(
            "app.application.use_cases.auth.refresh_token_use_case.create_access_token",
            return_value=("new-access-token", expires_at),
        ),
        patch(
            "app.application.use_cases.auth.refresh_token_use_case.create_refresh_token",
            return_value=("new-refresh-token", refresh_expires_at),
        ),
    ):
        result = await use_case.execute(
            RefreshTokenInputDTO(refresh_token="old-refresh-token"),
            client_ip="192.0.2.1",
        )

    token_repository.consume_valid_token.assert_awaited_once_with("old-refresh-token")
    token_repository.revoke.assert_not_awaited()
    token_repository.save.assert_awaited_once_with(
        token="new-refresh-token",
        user_id=user.id,
        expires_at=refresh_expires_at,
        created_from_ip="192.0.2.1",
    )
    assert result.access_token == "new-access-token"
    assert result.refresh_token == "new-refresh-token"


@pytest.mark.asyncio
async def test_refresh_losing_atomic_claim_cannot_issue_successor() -> None:
    user = _user()
    user_repository = AsyncMock()
    user_repository.get_by_id.return_value = user
    token_repository = AsyncMock()
    token_repository.get_valid_token.return_value = SimpleNamespace(user_id=user.id)
    token_repository.consume_valid_token.return_value = None
    use_case = RefreshTokenUseCase(user_repository, token_repository)

    with (
        patch(
            "app.application.use_cases.auth.refresh_token_use_case.create_access_token"
        ) as create_access_token,
        patch(
            "app.application.use_cases.auth.refresh_token_use_case.create_refresh_token"
        ) as create_refresh_token,
        pytest.raises(TokenExpiredError),
    ):
        await use_case.execute(RefreshTokenInputDTO(refresh_token="replayed-token"))

    create_access_token.assert_not_called()
    create_refresh_token.assert_not_called()
    token_repository.save.assert_not_awaited()
