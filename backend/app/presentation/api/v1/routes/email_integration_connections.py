"""Owned mailbox status, sync controls, opt-in and explicit account removal."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.email_integrations.overview import email_readiness
from app.application.use_cases.email_integrations.rollout_policy import (
    email_ai_disabled_policy_exists,
    email_ai_policy_allows,
)
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import AgencyModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.email.account_removal import purge_email_connection_records
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes import email_integration_policy_support as _policy_support
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailAiConnectionSettingsRequest,
    EmailAiConnectionSettingsResponse,
    EmailConnectionActionResponse,
    EmailConnectionResponse,
    EmailIntegrationStatusResponse,
    RemoveEmailConnectionRequest,
    RemoveEmailConnectionResponse,
)
from app.presentation.dependencies.csrf import require_cookie_csrf

from .email_integration_access import (
    _agency_scope,
    _current_email_user,
    _email_owner_filters,
    _enqueue_connection_sync,
    _owned_connection,
    _provider_instance,
)
from .email_integration_credentials import (
    fence_connection_sync,
    revocation_credential,
    revoke_provider_credential,
)

router = APIRouter()
logger = get_logger(__name__)

_provider_configured = _policy_support._provider_configured
_require_feature = _policy_support._require_feature
_allowed_connection_actions = _policy_support._allowed_connection_actions
_email_removal_confirmation_matches = _policy_support._email_removal_confirmation_matches


@router.get("/status", response_model=EmailIntegrationStatusResponse)
async def email_integration_status(
    current_user: User = Depends(_current_email_user),
) -> EmailIntegrationStatusResponse:
    del current_user
    return EmailIntegrationStatusResponse.model_validate(email_readiness(get_settings()))


@router.get("/connections", response_model=list[EmailConnectionResponse])
async def list_email_connections(
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[EmailConnectionResponse]:
    settings = get_settings()
    result = await session.execute(
        select(
            EmailConnectionModel,
            AgencyModel.name,
            (
                ~email_ai_disabled_policy_exists(
                    agency_id=EmailConnectionModel.agency_id,
                    owner_user_id=EmailConnectionModel.owner_user_id,
                    connection_id=EmailConnectionModel.id,
                )
            ).label("ai_policy_allows"),
        )
        .join(AgencyModel, AgencyModel.id == EmailConnectionModel.agency_id)
        .where(
            *_email_owner_filters(
                EmailConnectionModel.owner_user_id,
                EmailConnectionModel.agency_id,
                current_user,
            )
        )
        .order_by(EmailConnectionModel.created_at.desc())
    )
    return [
        EmailConnectionResponse(
            id=connection.id,
            agency_id=connection.agency_id,
            agency_name=agency_name,
            provider=connection.provider,
            email_address=connection.email_address,
            status=connection.status,
            last_successful_sync_at=connection.last_successful_sync_at,
            last_sync_attempt_at=connection.last_sync_attempt_at,
            last_error_message=connection.last_error_message,
            ai_processing_enabled=connection.ai_processing_enabled,
            ai_effective_enabled=bool(
                connection.ai_processing_enabled
                and settings.email_ai_runtime_ready
                and connection.status in {"active", "failing"}
                and ai_policy_allows
            ),
            allowed_actions=_allowed_connection_actions(connection, settings),
        )
        for connection, agency_name, ai_policy_allows in result.all()
    ]


@router.post(
    "/connections/{connection_id}/sync",
    response_model=EmailConnectionActionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def sync_connection(
    connection_id: uuid.UUID,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailConnectionActionResponse:
    settings = get_settings()
    _require_feature(settings)
    if not settings.email_sync_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email synchronization is disabled.",
        )
    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=_agency_scope(current_user),
        for_update=True,
    )
    if connection.status not in {"active", "failing"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resume or reconnect this email account before syncing.",
        )
    connection.sync_state = "queued"
    connection.next_sync_at = datetime.now(tz=UTC)
    await session.commit()
    queued = _enqueue_connection_sync(connection)
    return EmailConnectionActionResponse(
        connection_id=connection.id,
        status=connection.status,
        message=(
            "Email synchronization was queued."
            if queued
            else "Email synchronization is scheduled for the next worker cycle."
        ),
    )


@router.post(
    "/connections/{connection_id}/pause",
    response_model=EmailConnectionActionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def pause_connection(
    connection_id: uuid.UUID,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailConnectionActionResponse:
    agency_id = _agency_scope(current_user)
    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=agency_id,
        for_update=True,
    )
    agency_id = connection.agency_id
    if connection.status == "disconnected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reconnect this email account before pausing it.",
        )
    now = datetime.now(tz=UTC)
    connection.status = "paused"
    connection.sync_state = "idle"
    connection.sync_generation += 1
    connection.sync_lease_token = None
    connection.sync_lease_expires_at = None
    connection.next_sync_at = None
    connection.paused_at = now
    await AuditLogRepository(session).record(
        action="email_connection_paused",
        entity_type="email_connection",
        entity_id=str(connection.id),
        agency_id=agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={"provider": connection.provider},
    )
    return EmailConnectionActionResponse(
        connection_id=connection.id,
        status=connection.status,
        message="Email monitoring is paused for this account.",
    )


@router.post(
    "/connections/{connection_id}/resume",
    response_model=EmailConnectionActionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def resume_connection(
    connection_id: uuid.UUID,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailConnectionActionResponse:
    settings = get_settings()
    _require_feature(settings)
    if not settings.email_sync_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email synchronization is disabled.",
        )
    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=_agency_scope(current_user),
        for_update=True,
    )
    if connection.status != "paused":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a paused email connection can be resumed.",
        )
    connection.status = "active"
    connection.sync_state = "queued"
    connection.sync_generation += 1
    connection.next_sync_at = datetime.now(tz=UTC)
    connection.paused_at = None
    await session.commit()
    queued = _enqueue_connection_sync(connection)
    return EmailConnectionActionResponse(
        connection_id=connection.id,
        status=connection.status,
        message=(
            "Email monitoring resumed and synchronization was queued."
            if queued
            else "Email monitoring resumed; synchronization will start next cycle."
        ),
    )


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


@router.put(
    "/connections/{connection_id}/ai-settings",
    response_model=EmailAiConnectionSettingsResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_connection_ai_settings(
    connection_id: uuid.UUID,
    payload: EmailAiConnectionSettingsRequest,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailAiConnectionSettingsResponse:
    """Opt the authenticated owner's mailbox into or out of AI analysis."""

    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=current_user.agency_id,
        for_update=True,
    )
    now = datetime.now(tz=UTC)
    was_enabled = connection.ai_processing_enabled
    connection.ai_processing_enabled = payload.enabled
    connection.updated_at = now
    if payload.enabled and (not was_enabled or connection.ai_enabled_at is None):
        # New analysis starts at an explicit opt-in watermark. Historical
        # backfill is intentionally a separate future operation.
        connection.ai_enabled_at = now
    if not payload.enabled:
        await session.execute(
            update(EmailAiAnalysisModel)
            .where(
                EmailAiAnalysisModel.connection_id == connection.id,
                EmailAiAnalysisModel.agency_id == connection.agency_id,
                EmailAiAnalysisModel.owner_user_id == current_user.id,
                EmailAiAnalysisModel.status.in_({"pending", "processing"}),
            )
            .values(
                status="ignored",
                needs_attention=False,
                lease_token=None,
                lease_expires_at=None,
                next_attempt_at=None,
                started_at=None,
                completed_at=now,
                last_error_code="account_ai_opted_out",
            )
            .execution_options(synchronize_session=False)
        )
    await AuditLogRepository(session).record(
        agency_id=connection.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        action=("email_ai.account_enabled" if payload.enabled else "email_ai.account_disabled"),
        entity_type="email_connection",
        entity_id=str(connection.id),
        metadata={"provider": connection.provider},
    )
    settings = get_settings()
    effective_enabled = bool(
        payload.enabled
        and settings.email_ai_runtime_ready
        and connection.status in {"active", "failing"}
        and await email_ai_policy_allows(
            session,
            agency_id=connection.agency_id,
            owner_user_id=current_user.id,
            connection_id=connection.id,
        )
    )
    if effective_enabled:
        message = "Travel email analysis is active for this account."
    elif payload.enabled:
        message = (
            "This account is opted in, but an organization, user, account, "
            "deployment, or mailbox safety control is keeping analysis inactive."
        )
    else:
        message = "Travel email analysis is off for this account."
    return EmailAiConnectionSettingsResponse(
        connection_id=connection.id,
        enabled=payload.enabled,
        effective_enabled=effective_enabled,
        message=message,
    )
