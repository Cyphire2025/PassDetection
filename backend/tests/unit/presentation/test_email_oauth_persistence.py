"""Provider callback persistence remains atomic after route decomposition."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.fernet import Fernet
from fastapi import Request

from app.application.interfaces.email_provider import EmailAccountProfile, EmailTokenSet
from app.core.config.settings import Settings
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.email.token_encryption import EmailTokenCipher, EncryptedToken
from app.presentation.api.v1.routes import email_integration_gmail as gmail
from app.presentation.api.v1.routes import email_integration_outlook as outlook


@pytest.mark.parametrize("provider_name", ["gmail", "outlook"])
@pytest.mark.parametrize("reconnect", [False, True])
@pytest.mark.parametrize("identity_matches", [False, True])
async def test_callback_persists_only_matching_owned_grants_and_never_plaintext(
    monkeypatch,
    provider_name,
    reconnect,
    identity_matches,
) -> None:
    module = gmail if provider_name == "gmail" else outlook
    settings = Settings(
        app_env="development",
        app_secret_key="synthetic-oauth-secret",
        email_integrations_enabled=True,
        email_token_encryption_key=Fernet.generate_key().decode(),
        _env_file=None,
    )
    cipher = EmailTokenCipher.from_settings(settings)
    verifier = cipher.encrypt("synthetic-pkce-verifier")
    owner, agency = uuid.uuid4(), uuid.uuid4()
    state = SimpleNamespace(
        provider=provider_name,
        user_id=owner,
        agency_id=agency,
        connection_id=uuid.uuid4() if reconnect else None,
        consumed_at=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        code_verifier_ciphertext=verifier.ciphertext.encode(),
        key_version=verifier.key_version,
        nonce_hash="synthetic-browser-binding",
    )
    existing = EmailConnectionModel(
        id=state.connection_id or uuid.uuid4(),
        agency_id=agency,
        owner_user_id=owner if identity_matches else uuid.uuid4(),
        provider=provider_name,
        provider_account_id="account" if identity_matches else "other-account",
        email_address="owner@example.test",
        sync_generation=8,
        refresh_token_ciphertext=cipher.encrypt("previous-refresh").ciphertext.encode(),
    )
    session = Mock(
        scalar=AsyncMock(side_effect=[state, owner, None if identity_matches else existing]),
        commit=AsyncMock(),
        rollback=AsyncMock(),
        add=Mock(),
        flush=AsyncMock(),
    )
    tokens = EmailTokenSet(
        access_token="synthetic-access", refresh_token="synthetic-refresh", scopes=("read-mail",)
    )
    provider = Mock(
        exchange_authorization_code=AsyncMock(return_value=tokens),
        get_account_profile=AsyncMock(
            return_value=EmailAccountProfile(
                provider_account_id="account",
                email_address="OWNER@example.test",
                display_name="Owner",
            )
        ),
        revoke_token=AsyncMock(),
    )
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(module, "_provider_configured", lambda *_: True)
    monkeypatch.setattr(
        module,
        "GmailEmailProvider" if provider_name == "gmail" else "OutlookEmailProvider",
        lambda **_: provider,
    )
    monkeypatch.setattr(module, "verify_oauth_browser_binding", AsyncMock(return_value=True))
    monkeypatch.setattr(
        module, "revalidate_oauth_actor_for_persistence", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(module, "_owned_connection", AsyncMock(return_value=existing))
    audit = AsyncMock()
    monkeypatch.setattr(module, "AuditLogRepository", lambda _: SimpleNamespace(record=audit))
    queue = Mock()
    monkeypatch.setattr(module, "_enqueue_connection_sync", queue)
    callback = getattr(module, f"{provider_name}_oauth_callback")
    response = await callback(
        Request({"type": "http", "headers": []}), "a" * 43, "synthetic-code", None, session
    )
    assert state.consumed_at is not None
    assert response.status_code == 303
    assert "synthetic-code" not in response.headers["location"]
    if not identity_matches:
        assert "email_oauth=failed" in response.headers["location"]
        session.rollback.assert_awaited_once()
        audit.assert_not_awaited()
        queue.assert_not_called()
        if provider_name == "gmail":
            provider.revoke_token.assert_awaited_once_with(token="synthetic-refresh")
        else:
            provider.revoke_token.assert_not_awaited()  # Outlook's provider contract has no revocation API.
        return
    connection = existing if reconnect else session.add.call_args.args[0]
    assert connection.owner_user_id == owner and connection.agency_id == agency
    assert connection.email_address == "OWNER@example.test"
    assert connection.normalized_email_address == "owner@example.test"
    assert connection.status == "active" and connection.sync_state == "queued"
    assert connection.sync_generation == (9 if reconnect else 1)
    for field, plaintext in (("access", "synthetic-access"), ("refresh", "synthetic-refresh")):
        value = getattr(connection, f"{field}_token_ciphertext")
        assert plaintext.encode() not in value
        assert (
            cipher.decrypt(
                EncryptedToken(ciphertext=value.decode(), key_version=connection.token_key_version)
            )
            == plaintext
        )
    assert session.commit.await_count == 2  # one-time state consumption, then authorized grant
    session.rollback.assert_not_awaited()
    queue.assert_called_once_with(connection)
    assert audit.await_args.kwargs["action"] == (
        "email_connection_reauthorized" if reconnect else "email_connection_created"
    )


@pytest.mark.parametrize("provider_name", ["gmail", "outlook"])
@pytest.mark.parametrize("state_value", [None, "bad"])
async def test_missing_or_malformed_oauth_state_does_not_read_or_write_database(
    monkeypatch, provider_name, state_value
):
    module = gmail if provider_name == "gmail" else outlook
    settings = Settings(
        app_env="development", app_secret_key="synthetic-oauth-secret", _env_file=None
    )
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    session = Mock(scalar=AsyncMock(), commit=AsyncMock(), add=Mock())
    response = await getattr(module, f"{provider_name}_oauth_callback")(
        Request({"type": "http", "headers": []}),
        state_value,
        "unused-code",
        None,
        session,
    )
    assert response.status_code == 303 and "email_oauth=failed" in response.headers["location"]
    session.scalar.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.add.assert_not_called()
