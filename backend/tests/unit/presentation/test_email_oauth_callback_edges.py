"""Provider-specific callback boundaries after shared grant-field extraction."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.fernet import Fernet
from fastapi import Request

from app.application.interfaces.email_provider import (
    EmailAccountProfile,
    EmailProviderError,
    EmailTokenSet,
)
from app.core.config.settings import Settings
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.email.token_encryption import EmailTokenCipher, EncryptedToken
from app.presentation.api.v1.routes import email_integration_gmail, email_integration_outlook


@pytest.fixture(params=["gmail", "outlook"])
def flow(request, monkeypatch):
    name = request.param
    module = email_integration_gmail if name == "gmail" else email_integration_outlook
    settings = Settings(
        app_env="development",
        app_secret_key="synthetic-callback-secret",
        email_integrations_enabled=True,
        email_token_encryption_key=Fernet.generate_key().decode(),
        _env_file=None,
    )
    cipher = EmailTokenCipher.from_settings(settings)
    owner, agency = uuid.uuid4(), uuid.uuid4()
    state = SimpleNamespace(
        provider=name,
        user_id=owner,
        agency_id=agency,
        connection_id=None,
        consumed_at=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        code_verifier_ciphertext=cipher.encrypt("synthetic-verifier").ciphertext.encode(),
        key_version=1,
        nonce_hash="synthetic-browser-binding",
    )
    connection = EmailConnectionModel(
        id=uuid.uuid4(),
        agency_id=agency,
        owner_user_id=owner,
        provider=name,
        provider_account_id="synthetic-account",
        email_address="owner@example.test",
        sync_generation=8,
        token_key_version=1,
        refresh_token_ciphertext=cipher.encrypt("previous-refresh").ciphertext.encode(),
    )
    provider = Mock(
        exchange_authorization_code=AsyncMock(
            return_value=EmailTokenSet(
                access_token="synthetic-access",
                refresh_token="synthetic-refresh",
                scopes=("read-mail",),
            )
        ),
        get_account_profile=AsyncMock(
            return_value=EmailAccountProfile(
                provider_account_id="synthetic-account",
                email_address="OWNER@example.test",
                display_name=None,
            )
        ),
        revoke_token=AsyncMock(),
    )
    session = Mock(
        scalar=AsyncMock(side_effect=[state, owner, None]),
        commit=AsyncMock(),
        rollback=AsyncMock(),
        add=Mock(),
        flush=AsyncMock(),
    )
    audit, queue, browser = AsyncMock(), Mock(), AsyncMock(return_value=True)
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(module, "_provider_configured", lambda *_: True)
    monkeypatch.setattr(
        module,
        "GmailEmailProvider" if name == "gmail" else "OutlookEmailProvider",
        lambda **_: provider,
    )
    monkeypatch.setattr(module, "verify_oauth_browser_binding", browser)
    monkeypatch.setattr(
        module, "revalidate_oauth_actor_for_persistence", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(module, "_owned_connection", AsyncMock(return_value=connection))
    monkeypatch.setattr(module, "AuditLogRepository", lambda _: SimpleNamespace(record=audit))
    monkeypatch.setattr(module, "_enqueue_connection_sync", queue)
    return SimpleNamespace(
        name=name,
        module=module,
        settings=settings,
        cipher=cipher,
        state=state,
        connection=connection,
        provider=provider,
        session=session,
        audit=audit,
        queue=queue,
        browser=browser,
    )


async def _invoke(flow, *, code="synthetic-code", error=None):
    return await getattr(flow.module, f"{flow.name}_oauth_callback")(
        Request({"type": "http", "headers": []}), "a" * 43, code, error, flow.session
    )


@pytest.mark.parametrize("rejected", ["absent", "expired", "consumed", "provider", "browser"])
async def test_rejected_state_never_exchanges_or_consumes_a_grant(flow, rejected):
    if rejected == "absent":
        flow.session.scalar.side_effect = [None]
    elif rejected == "expired":
        flow.state.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    elif rejected == "consumed":
        flow.state.consumed_at = datetime.now(UTC)
    elif rejected == "provider":
        flow.state.provider = "outlook" if flow.name == "gmail" else "gmail"
    else:
        flow.browser.return_value = False
    result = await _invoke(flow)
    assert result.status_code == 303 and "email_oauth=failed" in result.headers["location"]
    flow.session.commit.assert_not_awaited()
    flow.provider.exchange_authorization_code.assert_not_awaited()
    flow.session.add.assert_not_called()
    flow.queue.assert_not_called()


@pytest.mark.parametrize("stopped", ["denied", "cancelled", "missing-code", "disabled", "actor"])
async def test_consumed_state_stops_before_provider_on_denial_or_inactive_actor(flow, stopped):
    if stopped == "disabled":
        flow.settings.email_integrations_enabled = False
    if stopped == "actor":
        flow.session.scalar.side_effect = [flow.state, None]
    error = (
        "access_denied" if stopped == "denied" else "cancelled" if stopped == "cancelled" else None
    )
    result = await _invoke(
        flow, code=None if stopped == "missing-code" else "synthetic-code", error=error
    )
    expected = stopped if stopped in {"denied", "cancelled"} else "failed"
    assert f"email_oauth={expected}" in result.headers["location"]
    assert flow.state.consumed_at is not None
    flow.session.commit.assert_awaited_once()
    flow.provider.exchange_authorization_code.assert_not_awaited()
    flow.audit.assert_not_awaited()
    flow.queue.assert_not_called()


async def test_provider_exchange_failure_never_writes_or_queues_a_connection(flow):
    flow.provider.exchange_authorization_code.side_effect = EmailProviderError(
        "Synthetic exchange failure", code="SYNTHETIC", status_code=503
    )
    result = await _invoke(flow)
    assert "email_oauth=failed" in result.headers["location"]
    flow.session.add.assert_not_called()
    flow.session.flush.assert_not_awaited()
    flow.audit.assert_not_awaited()
    flow.queue.assert_not_called()


@pytest.mark.parametrize("existing", ["new", "explicit", "implicit", "implicit-without-refresh"])
async def test_no_new_refresh_token_preserves_only_an_existing_offline_grant(flow, existing):
    flow.provider.exchange_authorization_code.return_value = EmailTokenSet(
        access_token="synthetic-access"
    )
    if existing == "explicit":
        flow.state.connection_id = flow.connection.id
    elif existing.startswith("implicit"):
        if existing == "implicit-without-refresh":
            flow.connection.refresh_token_ciphertext = None
        flow.session.scalar.side_effect = [flow.state, flow.state.user_id, flow.connection]
    result = await _invoke(flow)
    if existing in {"new", "implicit-without-refresh"}:
        assert "email_oauth=failed" in result.headers["location"]
        flow.session.rollback.assert_awaited_once()
        flow.session.add.assert_not_called()
        flow.queue.assert_not_called()
        return
    assert "email_oauth=reconnected" in result.headers["location"]
    assert flow.connection.sync_generation == 9 and flow.connection.sync_cursor is None
    assert (
        flow.cipher.decrypt(
            EncryptedToken(
                ciphertext=flow.connection.refresh_token_ciphertext.decode(), key_version=1
            )
        )
        == "previous-refresh"
    )
    assert flow.connection.display_name is None
    flow.queue.assert_called_once_with(flow.connection)
    assert flow.session.commit.await_count == 2


async def test_reconnect_without_any_offline_grant_is_rejected(flow):
    flow.state.connection_id = flow.connection.id
    flow.connection.refresh_token_ciphertext = None
    flow.provider.exchange_authorization_code.return_value = EmailTokenSet(
        access_token="synthetic-access"
    )
    result = await _invoke(flow)
    assert "email_oauth=failed" in result.headers["location"]
    flow.session.rollback.assert_awaited_once()
    flow.session.flush.assert_not_awaited()
    flow.queue.assert_not_called()


async def test_reconnect_rejects_a_different_provider_before_applying_grant(flow):
    flow.state.connection_id = flow.connection.id
    flow.connection.provider = "outlook" if flow.name == "gmail" else "gmail"
    result = await _invoke(flow)
    assert "email_oauth=failed" in result.headers["location"]
    assert flow.connection.sync_generation == 8
    flow.session.rollback.assert_awaited_once()
    flow.audit.assert_not_awaited()


async def test_configuration_preflight_remains_provider_specific(flow, monkeypatch):
    monkeypatch.setattr(flow.module, "_provider_configured", lambda *_: False)
    result = await _invoke(flow)
    if flow.name == "outlook":
        assert "email_oauth=failed" in result.headers["location"]
        flow.session.commit.assert_awaited_once()
        flow.provider.exchange_authorization_code.assert_not_awaited()
    else:
        assert "email_oauth=connected" in result.headers["location"]
        flow.provider.exchange_authorization_code.assert_awaited_once()
        assert flow.session.commit.await_count == 2
        flow.queue.assert_called_once()


async def test_failed_cleanup_keeps_the_provider_specific_failed_redirect(flow):
    flow.state.connection_id = flow.connection.id
    flow.connection.provider = "outlook" if flow.name == "gmail" else "gmail"
    flow.provider.revoke_token.side_effect = EmailProviderError(
        "Synthetic cleanup failure", code="SYNTHETIC", status_code=503
    )
    result = await _invoke(flow)
    assert "email_oauth=failed" in result.headers["location"]
    assert flow.connection.sync_generation == 8
    flow.session.rollback.assert_awaited_once()
    flow.queue.assert_not_called()
    if flow.name == "gmail":
        flow.provider.revoke_token.assert_awaited_once_with(token="synthetic-refresh")
    else:
        flow.provider.revoke_token.assert_not_awaited()
