"""Owner opt-in watermarks and transactional revocation of in-flight AI work."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.email_integrations.rollout_policy import email_ai_policy_allows
from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailAiConnectionSettingsRequest,
    EmailAiConnectionSettingsResponse,
)
from app.presentation.dependencies.csrf import require_cookie_csrf

from .email_integration_access import _current_email_user, _owned_connection

router = APIRouter()


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


update_connection_ai_settings.__module__ = (
    "app.presentation.api.v1.routes.email_integration_connections"
)
