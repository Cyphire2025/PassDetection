"""Explicit mailbox removal with guarded provider and storage cleanup boundaries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.email.account_removal import purge_email_connection_records
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes import email_integration_policy_support as _policy_support
from app.presentation.api.v1.schemas.email_integration_schemas import (
    RemoveEmailConnectionRequest,
    RemoveEmailConnectionResponse,
)
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
logger = get_logger("app.presentation.api.v1.routes.email_integration_connections")
_email_removal_confirmation_matches = _policy_support._email_removal_confirmation_matches


@router.delete(
    "/connections/{connection_id}/data",
    response_model=RemoveEmailConnectionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def remove_email_connection_and_data(
    connection_id: uuid.UUID,
    payload: RemoveEmailConnectionRequest,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> RemoveEmailConnectionResponse:
    """Permanently remove one owned mailbox and its attributable data."""

    agency_scope = _agency_scope(current_user)
    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=agency_scope,
        for_update=True,
        with_tokens=True,
    )
    if not _email_removal_confirmation_matches(
        confirmation_email=payload.confirmation_email,
        connection_email=connection.email_address,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Type the connected email address exactly to confirm removal.",
        )

    agency_id = connection.agency_id
    provider = _provider_instance(connection.provider, get_settings())
    provider_name = connection.provider
    credentials_already_removed = (
        connection.status == "disconnected"
        and not connection.access_token_ciphertext
        and not connection.refresh_token_ciphertext
    )
    token_to_revoke, decryption_failed = (
        (None, False)
        if credentials_already_removed
        else revocation_credential(connection, provider)
    )

    # Commit the generation fence before contacting the provider. Any worker
    # already holding a stale claim will fail its ownership/generation checks.
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
            detail="This email connection changed while removing it. Retry the action.",
        )
    if revoke_error is not None:
        now = datetime.now(tz=UTC)
        connection.status = "disconnecting"
        connection.sync_state = "blocked"
        connection.next_sync_at = None
        connection.last_error_code = revoke_error.code[:80]
        connection.last_error_message = (
            "Provider access could not be revoked. Retry removing this account."
        )
        connection.last_error_at = now
        connection.updated_at = now
        await AuditLogRepository(session).record(
            action="email_connection_removal_failed",
            entity_type="email_connection",
            entity_id=str(connection.id),
            agency_id=agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "provider": provider_name,
                "error_code": revoke_error.code,
            },
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Provider access could not be revoked. The connection remains "
                "blocked; retry removing it."
            ),
        )

    try:
        removal = await purge_email_connection_records(
            session,
            connection=connection,
        )
        await AuditLogRepository(session).record(
            action="email_connection_data_removed",
            entity_type="email_connection",
            entity_id=str(removal.connection_id),
            agency_id=agency_id,
            user_id=current_user.id,
            actor_email=None,
            metadata={
                "provider": provider_name,
                "messages_removed": removal.message_count,
                "artifacts_removed": removal.artifact_count,
                "reviews_removed": removal.review_count,
                "activity_events_removed": removal.activity_count,
                "documents_removed": removal.document_count,
                "notifications_removed": removal.notification_count,
                "credential_disposition": "local_credentials_deleted",
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    storage_cleanup_pending = False
    if removal.storage_keys:
        try:
            await MinioStorageRepository().delete_files(list(removal.storage_keys))
        except Exception as exc:
            # Relational cleanup is already committed. The retention sweeper
            # safely removes these now-unreferenced objects on a later pass.
            storage_cleanup_pending = True
            logger.error(
                "email_connection_storage_cleanup_deferred",
                connection_id=str(removal.connection_id),
                object_count=len(removal.storage_keys),
                error_type=type(exc).__name__,
            )

    return RemoveEmailConnectionResponse(
        connection_id=removal.connection_id,
        messages_removed=removal.message_count,
        artifacts_removed=removal.artifact_count,
        reviews_removed=removal.review_count,
        activity_events_removed=removal.activity_count,
        documents_removed=removal.document_count,
        notifications_removed=removal.notification_count,
        storage_cleanup_pending=storage_cleanup_pending,
        message="The email account and its stored integration data were removed.",
    )


remove_email_connection_and_data.__module__ = (
    "app.presentation.api.v1.routes.email_integration_connections"
)
