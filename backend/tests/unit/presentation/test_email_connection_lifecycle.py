"""Credential fencing and consent invariants at the decomposed route boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException, Response

from app.application.interfaces.email_provider import EmailProviderError
from app.core.config.settings import Settings
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_models import EmailConnectionModel, EmailOAuthStateModel
from app.infrastructure.email.token_encryption import EmailTokenCipher, EncryptedToken
from app.presentation.api.v1.routes import (
    email_integration_connections as connections,
)
from app.presentation.api.v1.routes import (
    email_integration_credentials as credentials,
)
from app.presentation.api.v1.routes import (
    email_integration_gmail as gmail,
)
from app.presentation.api.v1.routes import (
    email_integration_oauth_start as consent,
)
from app.presentation.api.v1.routes import (
    email_integration_outlook as outlook,
)
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailAuthorizeRequest,
    RemoveEmailConnectionRequest,
)


def _actor() -> User:
    return User.create(
        email="owner@example.test",
        hashed_password="unused",
        full_name="Owner",
        role=UserRole.AGENCY_STAFF,
        agency_id=uuid.uuid4(),
    )


def _connection(actor: User) -> EmailConnectionModel:
    return EmailConnectionModel(
        id=uuid.uuid4(),
        agency_id=actor.agency_id,
        owner_user_id=actor.id,
        provider="gmail",
        provider_account_id="synthetic-account",
        email_address=actor.email,
        status="active",
        sync_state="running",
        sync_generation=8,
        sync_lease_token=uuid.uuid4(),
        sync_lease_expires_at=datetime.now(UTC),
        next_sync_at=datetime.now(UTC),
        access_token_ciphertext=b"encrypted-access",
        refresh_token_ciphertext=b"encrypted-refresh",
        token_key_version=1,
    )


@pytest.mark.parametrize("operation", ["disconnect", "remove"])
@pytest.mark.parametrize("provider_status", [None, 400, 401, 404, 429, 500])
async def test_disconnect_and_removal_commit_fence_before_remote_revoke(
    monkeypatch,
    operation,
    provider_status,
) -> None:
    actor = _actor()
    connection = _connection(actor)
    events: list[str] = []
    session = Mock(
        commit=AsyncMock(side_effect=lambda: events.append("commit")), rollback=AsyncMock()
    )
    owned = AsyncMock(return_value=connection)
    monkeypatch.setattr(connections, "_owned_connection", owned)
    monkeypatch.setattr(connections, "revocation_credential", lambda *_: ("synthetic-token", False))
    provider = Mock(supports_remote_token_revocation=True)

    async def revoke(*, token):
        assert token == "synthetic-token"
        assert events == ["commit"]
        assert connection.status == "disconnecting" and connection.sync_state == "blocked"
        assert connection.sync_generation == 9
        assert connection.sync_lease_token is None and connection.sync_lease_expires_at is None
        assert connection.next_sync_at is None
        events.append("provider")
        if provider_status is not None:
            raise EmailProviderError(
                "Synthetic provider rejection", code="SYNTHETIC", status_code=provider_status
            )

    provider.revoke_token = AsyncMock(side_effect=revoke)
    monkeypatch.setattr(connections, "_provider_instance", lambda *_: provider)
    audit = AsyncMock(side_effect=lambda **_: events.append("audit"))
    monkeypatch.setattr(connections, "AuditLogRepository", lambda _: SimpleNamespace(record=audit))
    removal = SimpleNamespace(
        connection_id=connection.id,
        message_count=1,
        artifact_count=2,
        review_count=3,
        activity_count=4,
        document_count=5,
        notification_count=6,
        storage_keys=(),
    )
    purge = AsyncMock(return_value=removal)
    monkeypatch.setattr(connections, "purge_email_connection_records", purge)

    async def invoke():
        if operation == "disconnect":
            return await connections.disconnect_email_connection(connection.id, actor, session)
        return await connections.remove_email_connection_and_data(
            connection.id,
            RemoveEmailConnectionRequest(confirmation_email=actor.email),
            actor,
            session,
        )

    if provider_status in {429, 500}:
        with pytest.raises(HTTPException) as failure:
            await invoke()
        assert failure.value.status_code == 503
        assert connection.status == "disconnecting"
        assert connection.refresh_token_ciphertext == b"encrypted-refresh"
        purge.assert_not_awaited()
        assert events[-1] == "commit"  # durable blocked state survives provider failure
    else:
        result = await invoke()
        if operation == "disconnect":
            assert result.status_code == 204
            assert (
                connection.access_token_ciphertext is None
                and connection.refresh_token_ciphertext is None
            )
            purge.assert_not_awaited()
        else:
            assert result.messages_removed == 1 and result.documents_removed == 5
            purge.assert_awaited_once_with(session, connection=connection)
        assert events == ["commit", "provider", "audit", "commit"]
    assert len(owned.await_args_list) == 2
    for call in owned.await_args_list:
        assert call.kwargs["owner_user_id"] == actor.id
        assert call.kwargs["agency_id"] == actor.agency_id
        assert call.kwargs["for_update"] is True and call.kwargs["with_tokens"] is True


@pytest.mark.parametrize("remote", [True, False])
@pytest.mark.parametrize("stored", ["refresh", "access", "none", "invalid"])
async def test_revocation_credential_uses_real_encryption_and_fails_closed(
    monkeypatch, remote, stored
):
    cipher = EmailTokenCipher(key=Fernet.generate_key().decode(), key_version=1)
    monkeypatch.setattr(credentials.EmailTokenCipher, "from_settings", lambda: cipher)
    connection = _connection(_actor())
    connection.refresh_token_ciphertext = None
    connection.access_token_ciphertext = None
    if stored in {"refresh", "access"}:
        setattr(
            connection, f"{stored}_token_ciphertext", cipher.encrypt(stored).ciphertext.encode()
        )
    elif stored == "invalid":
        connection.refresh_token_ciphertext = b"\xff"
    provider = Mock(supports_remote_token_revocation=remote, revoke_token=AsyncMock())
    token, failed = credentials.revocation_credential(connection, provider)
    assert failed is (remote and stored == "invalid")
    assert token == (stored if remote and stored in {"refresh", "access"} else None)
    error = await credentials.revoke_provider_credential(provider, token, failed)
    if failed:
        assert error.code == "EMAIL_TOKEN_DECRYPTION_FAILED"
        provider.revoke_token.assert_not_awaited()
    elif token is None:
        provider.revoke_token.assert_not_awaited()


@pytest.mark.parametrize("provider_name", ["gmail", "outlook"])
@pytest.mark.parametrize("reconnect", [False, True])
async def test_consent_start_binds_owner_browser_generation_and_encrypts_verifier(
    monkeypatch, provider_name, reconnect
):
    actor = _actor()
    settings = Settings(
        app_env="development",
        app_secret_key="synthetic-consent-secret",
        email_integrations_enabled=True,
        email_token_encryption_key=Fernet.generate_key().decode(),
        _env_file=None,
    )
    monkeypatch.setattr(consent, "get_settings", lambda: settings)
    monkeypatch.setattr(consent, "_provider_configured", lambda *_: True)
    connection = _connection(actor)
    connection.provider = provider_name
    owned = AsyncMock(return_value=connection)
    monkeypatch.setattr(consent, "_owned_connection", owned)
    provider = Mock(
        build_authorization_url=Mock(return_value="https://provider.example.test/consent")
    )
    monkeypatch.setattr(consent, "_provider_instance", lambda *_: provider)
    audit = AsyncMock()
    monkeypatch.setattr(consent, "AuditLogRepository", lambda _: SimpleNamespace(record=audit))
    session = Mock(add=Mock(), commit=AsyncMock())
    response = Response()
    authorize = gmail.authorize_gmail if provider_name == "gmail" else outlook.authorize_outlook
    result = await authorize(
        EmailAuthorizeRequest(connection_id=connection.id if reconnect else None),
        response,
        actor,
        session,
    )
    assert result.authorization_url == "https://provider.example.test/consent"
    state = session.add.call_args.args[0]
    assert isinstance(state, EmailOAuthStateModel)
    assert (state.provider, state.user_id, state.agency_id) == (
        provider_name,
        actor.id,
        actor.agency_id,
    )
    assert state.nonce_hash and state.state_hash and state.consumed_at is None
    assert "HttpOnly" in response.headers["set-cookie"]
    assert f"email_oauth_{provider_name}=" in response.headers["set-cookie"]
    verifier = EmailTokenCipher.from_settings(settings).decrypt(
        EncryptedToken(
            ciphertext=state.code_verifier_ciphertext.decode(),
            key_version=state.key_version,
        )
    )
    assert len(verifier) >= 43 and verifier.encode() != state.code_verifier_ciphertext
    assert audit.await_args.kwargs["metadata"] == {
        "provider": provider_name,
        "reconnect": reconnect,
    }
    session.commit.assert_not_awaited()  # request dependency owns consent transaction
    if reconnect:
        assert owned.await_args.kwargs["owner_user_id"] == actor.id
        assert owned.await_args.kwargs["agency_id"] == actor.agency_id


@pytest.mark.parametrize("provider_name", ["gmail", "outlook"])
async def test_cross_provider_reconnect_is_rejected_before_consent(monkeypatch, provider_name):
    actor = _actor()
    monkeypatch.setattr(
        consent, "get_settings", lambda: SimpleNamespace(email_integrations_enabled=True)
    )
    monkeypatch.setattr(consent, "_provider_configured", lambda *_: True)
    connection = _connection(actor)
    connection.provider = "outlook" if provider_name == "gmail" else "gmail"
    monkeypatch.setattr(consent, "_owned_connection", AsyncMock(return_value=connection))
    session = Mock(add=Mock())
    with pytest.raises(HTTPException) as failure:
        await consent.begin_provider_authorization(
            provider_name,
            EmailAuthorizeRequest(connection_id=connection.id),
            Response(),
            actor,
            session,
        )
    assert failure.value.status_code == 400
    session.add.assert_not_called()
