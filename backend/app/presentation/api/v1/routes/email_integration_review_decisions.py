"""Serialized staff review decisions and their durable audit/storage effects."""

from __future__ import annotations

import uuid as uuid
from datetime import UTC as UTC
from datetime import datetime as datetime
from datetime import timedelta as timedelta

from fastapi import APIRouter as APIRouter
from fastapi import Depends as Depends
from fastapi import HTTPException as HTTPException
from fastapi import status as status
from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy as AuthorizationPolicy
from app.core.config.settings import get_settings as get_settings
from app.domain.entities.entities import User as User
from app.domain.entities.entities import UserRole as UserRole
from app.infrastructure.database.email_models import (
    EmailActivityEventModel as EmailActivityEventModel,
)
from app.infrastructure.database.email_models import EmailArtifactModel as EmailArtifactModel
from app.infrastructure.database.email_models import EmailMessageModel as EmailMessageModel
from app.infrastructure.database.email_models import EmailReviewItemModel as EmailReviewItemModel
from app.infrastructure.database.models import ClientGroupModel as ClientGroupModel
from app.infrastructure.database.models import PassportSubmissionModel as PassportSubmissionModel
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.email.review_decisions import (
    mark_message_unrelated as mark_message_unrelated,
)
from app.infrastructure.email.sync_service import (
    ingest_reviewed_artifact as ingest_reviewed_artifact,
)
from app.infrastructure.email.sync_service import (
    refresh_message_processing_state as refresh_message_processing_state,
)
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepository,
)
from app.infrastructure.storage.minio_repository import (
    MinioStorageRepository as MinioStorageRepository,
)
from app.presentation.api.v1.routes import email_integration_policy_support as _policy_support
from app.presentation.api.v1.routes import email_integration_review_support as _review_support
from app.presentation.api.v1.routes.email_review_actions import _apply_email_review_action
from app.presentation.api.v1.routes.email_review_context import _lock_email_review
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailReviewActionResponse as EmailReviewActionResponse,
)
from app.presentation.api.v1.schemas.email_integration_schemas import (
    ResolveEmailReviewRequest as ResolveEmailReviewRequest,
)
from app.presentation.dependencies.csrf import require_cookie_csrf as require_cookie_csrf

from .email_integration_access import _ACTIVE_REVIEW_STATUSES as _ACTIVE_REVIEW_STATUSES
from .email_integration_access import _current_email_user as _current_email_user
from .email_integration_access import _email_owner_filters as _email_owner_filters
from .email_integration_access import _enqueue_connection_sync as _enqueue_connection_sync
from .email_integration_access import _owned_connection as _owned_connection

router = APIRouter()

_require_feature = _policy_support._require_feature
_allowed_review_actions = _review_support._allowed_review_actions


@router.post(
    "/reviews/{review_id}/resolve",
    response_model=EmailReviewActionResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def resolve_email_review(
    review_id: uuid.UUID,
    payload: ResolveEmailReviewRequest,
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailReviewActionResponse:
    settings = get_settings()
    if payload.action in {"approve", "assign", "retry"}:
        _require_feature(settings)
    if payload.action == "retry" and not settings.email_sync_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email synchronization is disabled.",
        )

    locked = await _lock_email_review(
        session,
        review_id=review_id,
        payload=payload,
        current_user=current_user,
    )
    connection = locked.connection
    message = locked.message
    artifact = locked.artifact
    review = locked.review
    agency_id = locked.agency_id

    now = datetime.now(tz=UTC)
    outcome = await _apply_email_review_action(
        session,
        locked=locked,
        payload=payload,
        current_user=current_user,
        now=now,
    )
    should_queue_retry = outcome.should_queue_retry
    created_storage_keys = outcome.created_storage_keys
    result_message = outcome.result_message

    review.resolved_by_user_id = None if payload.action == "defer" else current_user.id
    review.revision += 1
    review.updated_at = now
    session.add(
        EmailActivityEventModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            owner_user_id=current_user.id,
            connection_id=message.connection_id,
            message_id=message.id,
            artifact_id=artifact.id if artifact else None,
            review_item_id=review.id,
            event_key=f"{review.id}:resolved:{review.revision}",
            event_type="review_decision",
            stage="info" if payload.action == "defer" else "success",
            actor_type="user",
            actor_user_id=current_user.id,
            summary_code=f"EMAIL_REVIEW_{payload.action.upper()}",
            details={"action": payload.action},
            ai_used=False,
            changed_entity_type="email_review",
            changed_entity_id=review.id,
            occurred_at=now,
            created_at=now,
        )
    )
    try:
        await AuditLogRepository(session).record(
            action=f"email_review_{payload.action}",
            entity_type="email_review",
            entity_id=str(review.id),
            agency_id=agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "review_type": review.review_type,
                "group_id": str(review.selected_group_id) if review.selected_group_id else None,
                "passenger_id": str(review.selected_passenger_id)
                if review.selected_passenger_id
                else None,
            },
        )
        await session.flush()
        await refresh_message_processing_state(session, message)
        if should_queue_retry:
            message.processing_status = "queued"
            message.processed_at = None
            message.updated_at = now
        await session.flush()
    except Exception:
        await session.rollback()
        if created_storage_keys:
            await MinioStorageRepository().delete_files(created_storage_keys)
        raise
    try:
        await session.commit()
    except Exception:
        # A failed COMMIT acknowledgement has an ambiguous outcome. Do not
        # delete objects that a successfully committed row may reference;
        # the email storage reconciler removes only proven orphans later.
        await session.rollback()
        raise
    if should_queue_retry:
        _enqueue_connection_sync(
            connection,
            provider_message_id=message.provider_message_id,
        )
    return EmailReviewActionResponse(
        review_id=review.id,
        status=review.status,
        message=result_message,
    )
