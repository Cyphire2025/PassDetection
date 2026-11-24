"""Owned mailbox synchronization, pause and resume transitions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes import email_integration_policy_support as _policy_support
from app.presentation.api.v1.schemas.email_integration_schemas import EmailConnectionActionResponse
from app.presentation.dependencies.csrf import require_cookie_csrf

from .email_integration_access import (
    _agency_scope,
    _current_email_user,
    _enqueue_connection_sync,
    _owned_connection,
)

router = APIRouter()
_require_feature = _policy_support._require_feature


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


sync_connection.__module__ = "app.presentation.api.v1.routes.email_integration_connections"
pause_connection.__module__ = "app.presentation.api.v1.routes.email_integration_connections"
resume_connection.__module__ = "app.presentation.api.v1.routes.email_integration_connections"
