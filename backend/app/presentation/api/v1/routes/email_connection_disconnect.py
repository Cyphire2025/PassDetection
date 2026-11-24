"""Credential revocation with committed worker and renewed-grant fences."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.dependencies.csrf import require_cookie_csrf

from .email_integration_access import (
    _agency_scope,
    _current_email_user,
    _owned_connection,
    _provider_instance,
)
from .email_integration_credentials import (
    fence_connection_sync,
    revocation_credential,
    revoke_provider_credential,
)

router = APIRouter()


@router.delete(
    "/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_cookie_csrf)],
)
async def disconnect_email_connection(
    connection_id: uuid.UUID,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    agency_id = _agency_scope(current_user)
    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=agency_id,
        for_update=True,
        with_tokens=True,
    )
    agency_id = connection.agency_id
    provider = _provider_instance(connection.provider, get_settings())
    if (
        connection.status == "disconnected"
        and not connection.access_token_ciphertext
        and not connection.refresh_token_ciphertext
    ):
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    token_to_revoke, decryption_failed = revocation_credential(connection, provider)

    now = datetime.now(tz=UTC)
    fence_connection_sync(connection, now)
    fenced_generation = connection.sync_generation
    await session.commit()

    revoke_error = await revoke_provider_credential(provider, token_to_revoke, decryption_failed)

    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=agency_id,
        for_update=True,
        with_tokens=True,
    )
    await session.refresh(connection, attribute_names=["sync_generation"])
    if connection.sync_generation != fenced_generation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email connection changed while disconnecting it. Retry the action.",
        )
    now = datetime.now(tz=UTC)
    if revoke_error is not None:
        connection.status = "disconnecting"
        connection.sync_state = "blocked"
        connection.next_sync_at = None
        connection.last_error_code = revoke_error.code[:80]
        connection.last_error_message = (
            "Provider access could not be revoked. Retry disconnecting this account."
        )
        connection.last_error_at = now
        connection.updated_at = now
        await AuditLogRepository(session).record(
            action="email_connection_disconnect_failed",
            entity_type="email_connection",
            entity_id=str(connection.id),
            agency_id=agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "provider": connection.provider,
                "error_code": revoke_error.code,
            },
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Provider access could not be revoked. The connection remains "
                "blocked; retry disconnecting it."
            ),
        )

    connection.status = "disconnected"
    connection.sync_state = "blocked"
    connection.access_token_ciphertext = None
    connection.refresh_token_ciphertext = None
    connection.token_expires_at = None
    connection.disconnected_at = now
    connection.last_error_code = None
    connection.last_error_message = None
    connection.last_error_at = None
    connection.updated_at = now
    await AuditLogRepository(session).record(
        action="email_connection_disconnected",
        entity_type="email_connection",
        entity_id=str(connection.id),
        agency_id=agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "provider": connection.provider,
            "provider_revoke_required": (
                provider.supports_remote_token_revocation and token_to_revoke is not None
            ),
            "provider_revoke_succeeded": (
                True
                if provider.supports_remote_token_revocation and token_to_revoke is not None
                else None
            ),
            "credential_disposition": "local_credentials_deleted",
        },
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


disconnect_email_connection.__module__ = (
    "app.presentation.api.v1.routes.email_integration_connections"
)
