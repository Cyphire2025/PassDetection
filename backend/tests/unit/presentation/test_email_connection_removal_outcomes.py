"""Removal rollback and post-commit object cleanup retain explicit boundaries."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_models import EmailConnectionModel
from app.presentation.api.v1.routes import email_connection_disconnect as disconnect
from app.presentation.api.v1.routes import email_connection_removal as removal
from app.presentation.api.v1.routes import email_integration_connections as api
from app.presentation.api.v1.schemas.email_integration_schemas import RemoveEmailConnectionRequest


@pytest.fixture
def mailbox(monkeypatch):
    actor = User.create(
        "owner@example.test", "unused", "Owner", UserRole.AGENCY_STAFF, agency_id=uuid.uuid4()
    )
    connection = EmailConnectionModel(
        id=uuid.uuid4(),
        agency_id=actor.agency_id,
        owner_user_id=actor.id,
        provider="outlook",
        provider_account_id="synthetic-account",
        email_address=actor.email,
        status="disconnected",
        sync_state="blocked",
        sync_generation=8,
        access_token_ciphertext=None,
        refresh_token_ciphertext=None,
    )
    provider = Mock(supports_remote_token_revocation=False)
    audit, owned, revoked = AsyncMock(), AsyncMock(return_value=connection), AsyncMock()
    for owner in (removal, disconnect):
        monkeypatch.setattr(owner, "_owned_connection", owned)
        monkeypatch.setattr(owner, "_provider_instance", lambda *_: provider)
        monkeypatch.setattr(owner, "AuditLogRepository", lambda _: SimpleNamespace(record=audit))
        monkeypatch.setattr(owner, "revoke_provider_credential", revoked)
    counts = SimpleNamespace(
        connection_id=connection.id,
        message_count=1,
        artifact_count=2,
        review_count=3,
        activity_count=4,
        document_count=5,
        notification_count=6,
        storage_keys=("synthetic/unreferenced.pdf",),
    )
    purge = AsyncMock(return_value=counts)
    monkeypatch.setattr(removal, "purge_email_connection_records", purge)
    session = Mock(commit=AsyncMock(), rollback=AsyncMock(), refresh=AsyncMock())
    return actor, connection, owned, audit, revoked, purge, session


async def test_already_disconnected_mailbox_does_not_revoke_or_write(mailbox):
    actor, connection, owned, audit, revoked, _purge, session = mailbox
    result = await api.disconnect_email_connection(connection.id, actor, session)
    assert result.status_code == 204
    owned.assert_awaited_once()
    revoked.assert_not_awaited()
    audit.assert_not_awaited()
    session.refresh.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_wrong_removal_confirmation_never_reaches_provider_or_purge(mailbox):
    actor, connection, _owned, audit, revoked, purge, session = mailbox
    with pytest.raises(HTTPException) as failure:
        await api.remove_email_connection_and_data(
            connection.id,
            RemoveEmailConnectionRequest(confirmation_email="other@example.test"),
            actor,
            session,
        )
    assert failure.value.status_code == 400
    assert connection.sync_generation == 8
    revoked.assert_not_awaited()
    audit.assert_not_awaited()
    purge.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_object_cleanup_runs_only_after_database_removal_commit(
    mailbox, monkeypatch, cleanup_fails: bool
) -> None:
    actor, connection, _owned, audit, revoked, purge, session = mailbox
    events = []
    session.commit.side_effect = lambda: events.append("commit")
    revoked.return_value = None

    async def delete_files(keys):
        assert keys == ["synthetic/unreferenced.pdf"]
        assert events == ["commit", "commit"]
        events.append("storage")
        if cleanup_fails:
            raise OSError("Synthetic storage failure")

    cleanup = AsyncMock(side_effect=delete_files)
    monkeypatch.setattr(
        removal, "MinioStorageRepository", lambda: SimpleNamespace(delete_files=cleanup)
    )
    result = await api.remove_email_connection_and_data(
        connection.id, RemoveEmailConnectionRequest(confirmation_email=actor.email), actor, session
    )

    assert result.storage_cleanup_pending is cleanup_fails
    assert result.messages_removed == 1 and result.documents_removed == 5
    assert result.notifications_removed == 6
    purge.assert_awaited_once_with(session, connection=connection)
    assert audit.await_args.kwargs["actor_email"] is None
    assert (
        audit.await_args.kwargs["metadata"]["credential_disposition"] == "local_credentials_deleted"
    )
    session.rollback.assert_not_awaited()
    assert events == ["commit", "commit", "storage"]


async def test_database_removal_failure_rolls_back_and_never_deletes_objects(mailbox, monkeypatch):
    actor, connection, _owned, audit, revoked, purge, session = mailbox
    revoked.return_value = None
    purge.side_effect = ValueError("Synthetic relational failure")
    storage = Mock()
    monkeypatch.setattr(removal, "MinioStorageRepository", storage)
    with pytest.raises(ValueError, match="Synthetic relational failure"):
        await api.remove_email_connection_and_data(
            connection.id,
            RemoveEmailConnectionRequest(confirmation_email=actor.email),
            actor,
            session,
        )
    session.rollback.assert_awaited_once()
    session.commit.assert_awaited_once()  # only the pre-provider generation fence
    storage.assert_not_called()
    audit.assert_not_awaited()
