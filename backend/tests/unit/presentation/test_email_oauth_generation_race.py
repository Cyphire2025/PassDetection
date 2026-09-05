from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Request, Response
from sqlalchemy import update

from app.core.config.settings import Settings
from app.infrastructure.database.models import UserModel, UserSecurityStateModel
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.presentation.api.v1.routes import email_integrations
from app.presentation.security.email_oauth_binding import (
    OAuthBindingSnapshot,
    oauth_cookie_name,
    revalidate_oauth_actor_for_persistence,
    start_oauth_browser_binding,
)


@pytest.mark.parametrize("provider", ["gmail", "outlook"])
async def test_final_authorization_observes_generation_changed_after_initial_consent(
    db_session, provider: str
) -> None:
    user = UserModel(
        id=uuid.uuid4(),
        email="oauth-race@example.test",
        full_name="Synthetic",
        hashed_password="unused",
        role="super_admin",
        is_active=True,
    )
    state = UserSecurityStateModel(user_id=user.id, credential_state="active", session_version=3)
    db_session.add_all([user, state])
    await db_session.flush()
    response = Response()
    digest = start_oauth_browser_binding(
        response,
        provider=provider,
        user_id=user.id,
        session_version=3,
        settings=Settings(
            app_env="development", app_secret_key="synthetic-oauth-race-secret", _env_file=None
        ),
    )
    nonce = SimpleCookie(response.headers["set-cookie"])[oauth_cookie_name(provider)].value
    request = Request(
        {
            "type": "http",
            "headers": [(b"cookie", f"{oauth_cookie_name(provider)}={nonce}".encode())],
        }
    )
    binding = OAuthBindingSnapshot(provider=provider, user_id=user.id, nonce_hash=digest)
    assert await revalidate_oauth_actor_for_persistence(
        request, binding, agency_id=uuid.uuid4(), session=db_session
    )
    # Keep the security ORM object alive, then simulate a concurrent committed
    # generation update without synchronizing this session's identity map.
    await db_session.execute(
        update(UserSecurityStateModel)
        .where(UserSecurityStateModel.user_id == user.id)
        .values(session_version=4)
        .execution_options(synchronize_session=False)
    )
    assert state.session_version == 3
    assert not await revalidate_oauth_actor_for_persistence(
        request, binding, agency_id=uuid.uuid4(), session=db_session
    )
    assert state.session_version == 4


async def test_logout_all_increment_refreshes_previously_loaded_security_state(db_session) -> None:
    user = UserModel(
        id=uuid.uuid4(),
        email="logout-race@example.test",
        full_name="Synthetic",
        hashed_password="unused",
        role="super_admin",
        is_active=True,
    )
    state = UserSecurityStateModel(user_id=user.id, credential_state="active", session_version=3)
    db_session.add_all([user, state])
    await db_session.flush()
    await db_session.execute(
        update(UserSecurityStateModel)
        .where(UserSecurityStateModel.user_id == user.id)
        .values(session_version=4)
        .execution_options(synchronize_session=False)
    )
    assert state.session_version == 3
    await IdentitySecurityRepository(db_session).fence_sessions(user.id)
    assert state.session_version == 5


@pytest.mark.parametrize("provider_name", ["gmail", "outlook"])
async def test_callback_revalidates_after_exchange_before_writing_any_mailbox_grant(
    monkeypatch: pytest.MonkeyPatch, provider_name: str
) -> None:
    events = []
    user_id = uuid.uuid4()
    state = SimpleNamespace(
        provider=provider_name,
        user_id=user_id,
        agency_id=uuid.uuid4(),
        connection_id=None,
        consumed_at=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        code_verifier_ciphertext=b"synthetic-ciphertext",
        key_version=1,
        nonce_hash="binding",
    )
    session = Mock(
        scalar=AsyncMock(side_effect=[state, user_id]),
        commit=AsyncMock(),
        rollback=AsyncMock(),
        add=Mock(),
        flush=AsyncMock(),
    )
    token_set = SimpleNamespace(access_token="synthetic-access", refresh_token="synthetic-refresh")

    async def exchange(**_kwargs):
        events.append("provider_exchange")
        return token_set

    provider = Mock(
        exchange_authorization_code=exchange,
        get_account_profile=AsyncMock(return_value=Mock()),
        revoke_token=AsyncMock(),
    )
    cipher = Mock(
        decrypt=Mock(return_value="synthetic-verifier"), encrypt=Mock(return_value=Mock())
    )
    monkeypatch.setattr(
        email_integrations,
        "GmailEmailProvider" if provider_name == "gmail" else "OutlookEmailProvider",
        Mock(return_value=provider),
    )
    monkeypatch.setattr(
        email_integrations, "EmailTokenCipher", Mock(from_settings=Mock(return_value=cipher))
    )
    monkeypatch.setattr(
        email_integrations, "get_settings", lambda: SimpleNamespace(email_integrations_enabled=True)
    )
    monkeypatch.setattr(email_integrations, "_provider_configured", lambda *_: True)
    monkeypatch.setattr(
        email_integrations,
        "_oauth_return_url",
        lambda *_: "https://dashboard.example.test/settings?oauth=failed",
    )
    monkeypatch.setattr(
        email_integrations, "verify_oauth_browser_binding", AsyncMock(return_value=True)
    )

    async def revalidate(*args, **kwargs):
        events.append("final_authorization")
        return False

    monkeypatch.setattr(email_integrations, "revalidate_oauth_actor_for_persistence", revalidate)
    callback = getattr(email_integrations, f"{provider_name}_oauth_callback")
    response = await callback(
        request=Request({"type": "http", "headers": []}),
        state_value="s" * 43,
        code="synthetic-code",
        error=None,
        session=session,
    )
    assert response.status_code == 303
    assert "failed" in response.headers["location"]
    assert events == ["provider_exchange", "final_authorization"]
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
    session.rollback.assert_awaited_once()
    if provider_name == "gmail":
        provider.revoke_token.assert_awaited_once_with(token="synthetic-refresh")
