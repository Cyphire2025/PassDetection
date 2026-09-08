from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.application.dtos.auth_dtos import RefreshTokenInputDTO
from app.application.use_cases.auth.refresh_token_use_case import RefreshTokenUseCase
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthenticationError, TokenExpiredError


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
    mfa_at = datetime.now(tz=UTC)
    refresh_expires_at = mfa_at + timedelta(days=7)
    stored_token = SimpleNamespace(
        user_id=user.id,
        expires_at=refresh_expires_at,
        session_version=1,
        authentication_methods="pwd,totp",
        mfa_authenticated_at=mfa_at,
    )
    user_repository = AsyncMock()
    user_repository.get_by_id.return_value = user
    token_repository = AsyncMock()
    token_repository.get_valid_token.return_value = stored_token
    token_repository.consume_valid_token.return_value = stored_token
    use_case = RefreshTokenUseCase(user_repository, token_repository)
    expires_at = datetime.now(tz=UTC) + timedelta(minutes=30)

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
        session_version=1,
        authentication_methods=("pwd", "totp"),
        mfa_authenticated_at=mfa_at,
    )
    assert result.access_token == "new-access-token"
    assert result.refresh_token == "new-refresh-token"


@pytest.mark.asyncio
async def test_refresh_losing_atomic_claim_cannot_issue_successor() -> None:
    user = _user()
    mfa_at = datetime.now(tz=UTC)
    user_repository = AsyncMock()
    user_repository.get_by_id.return_value = user
    token_repository = AsyncMock()
    token_repository.get_valid_token.return_value = SimpleNamespace(
        user_id=user.id,
        expires_at=mfa_at + timedelta(days=7),
        session_version=1,
        authentication_methods="pwd,totp",
        mfa_authenticated_at=mfa_at,
    )
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


@pytest.mark.asyncio
@pytest.mark.parametrize("days_after_login", [1, 6])
async def test_rotation_keeps_original_weekly_deadline_and_mfa_time(days_after_login: int) -> None:
    user = _user()
    mfa_at = datetime.now(tz=UTC) - timedelta(days=days_after_login)
    deadline = mfa_at + timedelta(days=7)
    stored = SimpleNamespace(
        user_id=user.id, expires_at=deadline, session_version=4,
        authentication_methods="pwd,totp", mfa_authenticated_at=mfa_at,
    )
    users, tokens, security = AsyncMock(), AsyncMock(), AsyncMock()
    users.get_by_id.return_value = user
    tokens.get_valid_token.return_value = stored
    tokens.consume_valid_token.return_value = stored
    security.get_state.return_value = SimpleNamespace(credential_state="active", session_version=4)

    result = await RefreshTokenUseCase(users, tokens, security).execute(
        RefreshTokenInputDTO(refresh_token="old-opaque-token")
    )

    assert result.refresh_token_expires_at == deadline
    assert tokens.save.call_args.kwargs["expires_at"] == deadline
    assert tokens.save.call_args.kwargs["mfa_authenticated_at"] == mfa_at
    assert result.access_token_expires_at <= deadline


@pytest.mark.asyncio
async def test_legacy_sliding_refresh_cannot_extend_week_since_mfa() -> None:
    user = _user()
    now = datetime.now(tz=UTC)
    users, tokens = AsyncMock(), AsyncMock()
    users.get_by_id.return_value = user
    tokens.get_valid_token.return_value = SimpleNamespace(
        user_id=user.id, expires_at=now + timedelta(days=7), session_version=1,
        authentication_methods="pwd,totp", mfa_authenticated_at=now - timedelta(days=8),
    )
    with pytest.raises(TokenExpiredError):
        await RefreshTokenUseCase(users, tokens).execute(
            RefreshTokenInputDTO(refresh_token="legacy-sliding-token")
        )
    tokens.revoke.assert_awaited_once_with("legacy-sliding-token")
    tokens.consume_valid_token.assert_not_awaited()
    tokens.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_weekly_refresh_still_rejects_revoked_security_generation() -> None:
    user = _user()
    users, tokens, security = AsyncMock(), AsyncMock(), AsyncMock()
    users.get_by_id.return_value = user
    tokens.get_valid_token.return_value = SimpleNamespace(
        user_id=user.id, expires_at=datetime.now(tz=UTC) + timedelta(days=6),
        session_version=1, authentication_methods="pwd,totp",
        mfa_authenticated_at=datetime.now(tz=UTC),
    )
    security.get_state.return_value = SimpleNamespace(credential_state="active", session_version=2)
    with pytest.raises(AuthenticationError, match="Session is no longer valid"):
        await RefreshTokenUseCase(users, tokens, security).execute(
            RefreshTokenInputDTO(refresh_token="revoked-generation-token")
        )
    tokens.revoke.assert_awaited_once_with("revoked-generation-token")
    tokens.consume_valid_token.assert_not_awaited()
    tokens.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_privileged_pre_mfa_refresh_token_is_revoked_during_rollout() -> None:
    user = _user()
    user_repository = AsyncMock()
    user_repository.get_by_id.return_value = user
    token_repository = AsyncMock()
    token_repository.get_valid_token.return_value = SimpleNamespace(
        user_id=user.id,
        session_version=1,
        authentication_methods="pwd",
        mfa_authenticated_at=None,
    )
    use_case = RefreshTokenUseCase(user_repository, token_repository)

    with pytest.raises(AuthenticationError, match="MFA sign-in is required"):
        await use_case.execute(RefreshTokenInputDTO(refresh_token="pre-mfa-token"))

    token_repository.revoke.assert_awaited_once_with("pre-mfa-token")
    token_repository.consume_valid_token.assert_not_awaited()
    token_repository.save.assert_not_awaited()
