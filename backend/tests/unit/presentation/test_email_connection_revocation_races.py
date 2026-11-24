"""Ordinary renewed-grant interleavings at the post-provider transaction boundary."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import undefer

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import AgencyModel, UserModel
from app.presentation.api.v1.routes import email_connection_disconnect, email_connection_removal
from app.presentation.api.v1.routes import email_integration_connections as connections
from app.presentation.api.v1.schemas.email_integration_schemas import RemoveEmailConnectionRequest


@pytest.mark.parametrize("operation", ["disconnect", "remove"])
@pytest.mark.parametrize("grant_renewed", [False, True])
async def test_old_revocation_does_not_finalize_against_a_renewed_grant(
    db_session, monkeypatch, operation: str, grant_renewed: bool
) -> None:
    actor = User.create(
        "owner@example.test", "unused", "Owner", UserRole.AGENCY_STAFF, agency_id=uuid.uuid4()
    )
    db_session.add(AgencyModel(id=actor.agency_id, name="Synthetic", email="agency@example.test"))
    await db_session.flush()
    db_session.add(
        UserModel(
            id=actor.id,
            agency_id=actor.agency_id,
            email=actor.email,
            full_name=actor.full_name,
            role=actor.role.value,
            hashed_password="unused",
        )
    )
    await db_session.flush()
    connection = EmailConnectionModel(
        id=uuid.uuid4(),
        agency_id=actor.agency_id,
        owner_user_id=actor.id,
        provider="gmail",
        provider_account_id="synthetic-account",
        email_address=actor.email,
        access_token_ciphertext=b"previous-encrypted-access",
        refresh_token_ciphertext=b"previous-encrypted-refresh",
        sync_generation=8,
        status="active",
        sync_state="idle",
        created_by_user_id=actor.id,
    )
    db_session.add(connection)
    await db_session.commit()
    connection_id = connection.id
    route_owner = (
        email_connection_disconnect if operation == "disconnect" else email_connection_removal
    )
    monkeypatch.setattr(route_owner, "revocation_credential", lambda *_: ("previous-grant", False))
    monkeypatch.setattr(
        route_owner, "AuditLogRepository", lambda _: SimpleNamespace(record=AsyncMock())
    )
    provider = Mock(supports_remote_token_revocation=True)

    async def revoke(*, token: str) -> None:
        assert token == "previous-grant"
        assert connection.sync_generation == 9 and connection.status == "disconnecting"
        if grant_renewed:
            # A completed, separately authorized reconnect writes a new generation
            # during the provider await. Bypass this session's identity map, as a
            # concurrent transaction does; do not simulate database row locks.
            await db_session.execute(
                update(EmailConnectionModel)
                .where(EmailConnectionModel.id == connection_id)
                .values(
                    status="active",
                    sync_state="queued",
                    sync_generation=10,
                    access_token_ciphertext=b"renewed-encrypted-access",
                    refresh_token_ciphertext=b"renewed-encrypted-refresh",
                )
                .execution_options(synchronize_session=False)
            )
            await db_session.commit()
            assert connection.sync_generation == 9  # retained ORM state is stale

    provider.revoke_token = AsyncMock(side_effect=revoke)
    monkeypatch.setattr(route_owner, "_provider_instance", lambda *_: provider)

    async def invoke():
        if operation == "disconnect":
            return await connections.disconnect_email_connection(connection_id, actor, db_session)
        return await connections.remove_email_connection_and_data(
            connection_id,
            RemoveEmailConnectionRequest(confirmation_email=actor.email),
            actor,
            db_session,
        )

    if grant_renewed:
        caught = None
        try:
            await invoke()
        except HTTPException as failure:
            caught = failure
        current = await db_session.scalar(
            select(EmailConnectionModel)
            .where(EmailConnectionModel.id == connection_id)
            .options(
                undefer(EmailConnectionModel.access_token_ciphertext),
                undefer(EmailConnectionModel.refresh_token_ciphertext),
            )
            .execution_options(populate_existing=True)
        )
        assert current is not None and current.sync_generation == 10
        assert current.status == "active" and current.sync_state == "queued"
        assert current.access_token_ciphertext == b"renewed-encrypted-access"
        assert current.refresh_token_ciphertext == b"renewed-encrypted-refresh"
        assert caught is not None and caught.status_code == 409
    else:
        result = await invoke()
        if operation == "disconnect":
            assert result.status_code == 204
            await db_session.refresh(
                connection,
                attribute_names=[
                    "status",
                    "sync_generation",
                    "access_token_ciphertext",
                    "refresh_token_ciphertext",
                ],
            )
            assert connection.status == "disconnected" and connection.sync_generation == 9
            assert (
                connection.access_token_ciphertext is None
                and connection.refresh_token_ciphertext is None
            )
        else:
            assert result.connection_id == connection_id
            assert await db_session.get(EmailConnectionModel, connection_id) is None
    provider.revoke_token.assert_awaited_once_with(token="previous-grant")
