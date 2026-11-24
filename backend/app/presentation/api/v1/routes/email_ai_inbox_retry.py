"""Retry for the owner-scoped email inbox."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.email_integrations.analysis_contract import EMAIL_AI_SCHEMA_VERSION
from app.application.use_cases.email_integrations.rollout_policy import email_ai_policy_allows
from app.domain.entities.entities import User
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.infrastructure.database.models import NotificationModel
from app.presentation.api.v1.routes import email_ai_inbox_activity as _activity
from app.presentation.api.v1.routes import email_ai_inbox_responses as _responses
from app.presentation.api.v1.routes import email_ai_inbox_scope as _scope
from app.presentation.api.v1.routes.email_ai_inbox_types import SettingsProvider
from app.presentation.api.v1.schemas.email_ai_schemas import EmailAiRetryResponse

_owner_predicates = _scope._owner_predicates
_aware_utc = _responses._aware_utc
_decision_activity_event = _activity._decision_activity_event


async def retry_email_ai_analysis(
    analysis_id: uuid.UUID,
    current_user: User,
    session: AsyncSession,
    get_settings: SettingsProvider,
) -> EmailAiRetryResponse:
    """Requeue one terminal owner-scoped analysis for a fresh bounded attempt cycle."""

    row = (
        await session.execute(
            select(
                EmailAiAnalysisModel,
                EmailConnectionModel,
                EmailMessageModel,
            )
            .join(
                EmailConnectionModel,
                and_(
                    EmailConnectionModel.id == EmailAiAnalysisModel.connection_id,
                    EmailConnectionModel.agency_id == EmailAiAnalysisModel.agency_id,
                    EmailConnectionModel.owner_user_id == EmailAiAnalysisModel.owner_user_id,
                ),
            )
            .join(
                EmailMessageModel,
                and_(
                    EmailMessageModel.id == EmailAiAnalysisModel.message_id,
                    EmailMessageModel.connection_id == EmailAiAnalysisModel.connection_id,
                    EmailMessageModel.agency_id == EmailAiAnalysisModel.agency_id,
                    EmailMessageModel.owner_user_id == EmailAiAnalysisModel.owner_user_id,
                ),
            )
            .where(
                EmailAiAnalysisModel.id == analysis_id,
                *_owner_predicates(EmailAiAnalysisModel, current_user),
            )
            .with_for_update(of=EmailAiAnalysisModel)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email intelligence was not found.",
        )
    analysis, connection, message = row
    if analysis.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a failed AI brief can be retried.",
        )

    settings = get_settings()
    if not settings.email_ai_runtime_ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Travel email analysis is not available in this deployment. No retry was queued."
            ),
        )
    if not connection.ai_processing_enabled or connection.status not in {"active", "failing"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("AI assistance is not active for this mailbox. No retry was queued."),
        )
    ai_enabled_at = _aware_utc(connection.ai_enabled_at)
    message_received_at = _aware_utc(message.received_at)
    if ai_enabled_at is None or message_received_at is None or message_received_at < ai_enabled_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This email predates the mailbox's current AI opt-in. "
                "It cannot be retried under the new consent period."
            ),
        )
    if not await email_ai_policy_allows(
        session,
        agency_id=analysis.agency_id,
        owner_user_id=analysis.owner_user_id,
        connection_id=analysis.connection_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("An organization, user, or mailbox safety control is blocking this retry."),
        )

    previous_result = analysis.result_json or {}
    retry_generation_value = previous_result.get("manual_retry_generation", 0)
    retry_generation = (
        retry_generation_value
        if isinstance(retry_generation_value, int)
        and not isinstance(retry_generation_value, bool)
        and retry_generation_value >= 0
        else 0
    ) + 1
    if retry_generation > settings.email_ai_max_manual_retries:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The manual retry limit has been reached. "
                "An operator must review the provider or deployment failure."
            ),
        )

    now = datetime.now(tz=UTC)
    previous_error_code = analysis.last_error_code
    await session.execute(
        update(NotificationModel)
        .where(
            NotificationModel.user_id == analysis.owner_user_id,
            NotificationModel.entity_type == "email_message",
            NotificationModel.entity_id == str(analysis.message_id),
            NotificationModel.dedupe_key.like(f"email-ai:{analysis.id}:%"),
            NotificationModel.is_read.is_(False),
        )
        .values(is_read=True, read_at=now)
        .execution_options(synchronize_session=False)
    )
    analysis.status = "pending"
    analysis.attempt_count = 0
    analysis.lease_token = None
    analysis.lease_expires_at = None
    analysis.next_attempt_at = None
    analysis.last_error_code = None
    analysis.started_at = None
    analysis.completed_at = None
    analysis.duration_ms = None
    analysis.intent = None
    analysis.priority = None
    analysis.summary = None
    analysis.confidence = None
    analysis.needs_attention = False
    analysis.context_manifest = {}
    analysis.result_json = {
        "manual_retry_generation": retry_generation,
        "manual_retry_requested_at": now.isoformat(),
        "previous_failure_code": previous_error_code,
    }
    analysis.prompt_schema_version = EMAIL_AI_SCHEMA_VERSION
    analysis.config_version = settings.gemini_config_version
    analysis.ai_model = settings.gemini_model
    analysis.updated_at = now
    session.add(
        _decision_activity_event(
            analysis=analysis,
            actor_user_id=current_user.id,
            event_key=(f"email-ai-analysis:{analysis.id}:retry:{retry_generation}"),
            event_type="ai_analysis_retry_requested",
            summary_code="email_ai_analysis_retry_requested",
            details={
                "analysis_id": str(analysis.id),
                "retry_generation": retry_generation,
                "max_runtime_attempts": settings.email_ai_max_attempts,
                "previous_error_code": previous_error_code,
                "external_action_performed": False,
            },
            changed_entity_type="email_ai_analysis",
            changed_entity_id=analysis.id,
            confidence=None,
        )
    )
    await session.flush()
    return EmailAiRetryResponse(
        analysis_id=analysis.id,
        status="pending",
        retry_generation=retry_generation,
        message=(
            "The AI brief is queued for a fresh bounded retry. The source email was not changed."
        ),
    )
