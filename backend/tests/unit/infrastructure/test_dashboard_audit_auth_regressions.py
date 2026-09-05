from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.auth.logout_all_use_case import LogoutAllUseCase
from app.core.config.settings import Settings
from app.core.security.jwt import create_access_token, decode_access_token, hash_refresh_token
from app.infrastructure.database.models import RefreshTokenModel, UserModel, UserSecurityStateModel
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.presentation.security.email_oauth_binding import (
    oauth_cookie_name,
    start_oauth_browser_binding,
    verify_oauth_browser_binding,
)


async def _account(session: AsyncSession) -> UserModel:
    user = UserModel(id=uuid.uuid4(), email="auth-audit@example.test", full_name="Audit fixture",
                     hashed_password="unused", role="super_admin", is_active=True)
    session.add(user)
    await session.flush()
    session.add(UserSecurityStateModel(user_id=user.id, credential_state="active", session_version=3))
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_database_digest_cannot_lookup_or_consume_real_refresh_row(db_session: AsyncSession) -> None:
    user = await _account(db_session)
    repository = RefreshTokenRepository(db_session)
    raw = str(uuid.uuid4())
    await repository.save(raw, user.id, datetime.now(UTC) + timedelta(days=1))
    stored_digest = hash_refresh_token(raw)
    assert await repository.get_valid_token(stored_digest) is None
    assert await repository.consume_valid_token(stored_digest) is None
    assert await repository.get_valid_token(raw) is not None
    assert await repository.consume_valid_token(raw) is not None
    assert await repository.consume_valid_token(raw) is None


@pytest.mark.asyncio
async def test_legacy_plaintext_row_is_never_accepted(db_session: AsyncSession) -> None:
    user = await _account(db_session)
    raw = str(uuid.uuid4())
    db_session.add(RefreshTokenModel(token=raw, user_id=user.id, expires_at=datetime.now(UTC)+timedelta(days=1)))
    await db_session.flush()
    repository = RefreshTokenRepository(db_session)
    assert await repository.get_valid_token(raw) is None
    assert await repository.consume_valid_token(raw) is None


@pytest.mark.asyncio
async def test_logout_all_fences_both_existing_access_sessions_and_refresh(db_session: AsyncSession) -> None:
    user = await _account(db_session)
    repository = RefreshTokenRepository(db_session)
    identity = IdentitySecurityRepository(db_session)
    tokens = [create_access_token(user_id=user.id, role=user.role, agency_id=None, session_version=3)[0]
              for _ in range(2)]
    for _ in range(2):
        await repository.save(str(uuid.uuid4()), user.id, datetime.now(UTC)+timedelta(days=1), session_version=3)
    await LogoutAllUseCase(repository, identity).execute(user.id)
    state = await identity.get_state(user.id)
    assert state.session_version == 4
    assert all(decode_access_token(token)["sv"] != state.session_version for token in tokens)
    assert not (await db_session.scalars(select(RefreshTokenModel).where(RefreshTokenModel.is_revoked.is_(False)))).all()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["gmail", "outlook"])
async def test_oauth_binding_requires_initiating_browser_and_live_generation(provider: str) -> None:
    response = Response()
    user_id = uuid.uuid4()
    settings = Settings(app_env="development", app_secret_key="oauth-test-secret", _env_file=None)
    digest = start_oauth_browser_binding(response, provider=provider, user_id=user_id, session_version=3, settings=settings)
    cookies = SimpleCookie(response.headers["set-cookie"])
    nonce = cookies[oauth_cookie_name(provider)].value
    assert cookies[oauth_cookie_name(provider)]["httponly"]
    assert cookies[oauth_cookie_name(provider)]["samesite"] == "lax"
    state = SimpleNamespace(provider=provider, user_id=user_id, nonce_hash=digest)
    browser_a = Request({"type":"http", "headers":[(b"cookie", f"{oauth_cookie_name(provider)}={nonce}".encode())]})
    browser_b = Request({"type":"http", "headers":[]})
    security = SimpleNamespace(credential_state="active", session_version=3)
    with patch.object(IdentitySecurityRepository, "get_state", AsyncMock(return_value=security)):
        assert not await verify_oauth_browser_binding(browser_b, state, AsyncMock())
        assert await verify_oauth_browser_binding(browser_a, state, AsyncMock())
        security.session_version = 4
        assert not await verify_oauth_browser_binding(browser_a, state, AsyncMock())
