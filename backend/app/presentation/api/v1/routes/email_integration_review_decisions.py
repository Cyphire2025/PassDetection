"""Serialized staff review decisions and their durable audit/storage effects."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailArtifactModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.email.review_decisions import mark_message_unrelated
from app.infrastructure.email.sync_service import (
    ingest_reviewed_artifact,
    refresh_message_processing_state,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes import email_integration_policy_support as _policy_support
from app.presentation.api.v1.routes import email_integration_review_support as _review_support
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailReviewActionResponse,
    ResolveEmailReviewRequest,
)
from app.presentation.dependencies.csrf import require_cookie_csrf

from .email_integration_access import (
    _ACTIVE_REVIEW_STATUSES,
    _current_email_user,
    _email_owner_filters,
    _enqueue_connection_sync,
    _owned_connection,
)

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
    review_identity = (
        await session.execute(
            select(
                EmailReviewItemModel.message_id,
                EmailReviewItemModel.artifact_id,
                EmailMessageModel.connection_id,
                EmailReviewItemModel.agency_id,
            )
            .join(
                EmailMessageModel,
                EmailMessageModel.id == EmailReviewItemModel.message_id,
            )
            .where(
                EmailReviewItemModel.id == review_id,
                *_email_owner_filters(
                    EmailReviewItemModel.owner_user_id,
                    EmailReviewItemModel.agency_id,
                    current_user,
                ),
                *_email_owner_filters(
                    EmailMessageModel.owner_user_id,
                    EmailMessageModel.agency_id,
                    current_user,
                ),
            )
        )
    ).one_or_none()
    if review_identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email review item was not found.",
        )
    message_id, artifact_id, connection_id, agency_id = review_identity

    # Match the worker's lock order: connection -> message -> artifact ->
    # review. This serializes sync and every staff decision for one mailbox
    # without review/message or message/connection lock inversions.
    connection = await _owned_connection(
        session,
        connection_id=connection_id,
        owner_user_id=current_user.id,
        agency_id=agency_id,
        for_update=True,
    )
    message = await session.scalar(
        select(EmailMessageModel)
        .where(
            EmailMessageModel.id == message_id,
            EmailMessageModel.agency_id == agency_id,
            EmailMessageModel.owner_user_id == current_user.id,
            EmailMessageModel.connection_id == connection.id,
        )
        .with_for_update()
    )
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The source email is no longer available.",
        )
    artifact = (
        await session.scalar(
            select(EmailArtifactModel)
            .where(
                EmailArtifactModel.id == artifact_id,
                EmailArtifactModel.agency_id == agency_id,
                EmailArtifactModel.owner_user_id == current_user.id,
                EmailArtifactModel.message_id == message.id,
            )
            .with_for_update()
        )
        if artifact_id
        else None
    )
    review = await session.scalar(
        select(EmailReviewItemModel)
        .where(
            EmailReviewItemModel.id == review_id,
            EmailReviewItemModel.agency_id == agency_id,
            EmailReviewItemModel.owner_user_id == current_user.id,
            EmailReviewItemModel.message_id == message.id,
        )
        .with_for_update()
    )
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email review item was not found.",
        )
    if review.revision != payload.expected_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This review item changed. Refresh it before deciding.",
        )
    if review.status not in _ACTIVE_REVIEW_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email review item is already closed.",
        )
    if payload.action not in _allowed_review_actions(review, artifact):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="That action is not available for this review item.",
        )
    now = datetime.now(tz=UTC)
    should_queue_retry = False
    created_storage_keys: list[str] = []

    if payload.action in {"approve", "assign"}:
        if artifact is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This review item has no document to assign.",
            )
        if artifact.detected_type not in {"visa", "flight_ticket"}:
            if (
                artifact.detected_type == "unknown"
                and payload.document_type in {"visa", "flight_ticket"}
                and artifact.storage_key
            ):
                artifact.detected_type = payload.document_type
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=("Choose a supported PDF document type before assigning this item."),
                )
        selected_group_id = payload.group_id or review.candidate_group_id
        selected_passenger_id = payload.passenger_id or review.candidate_passenger_id
        if selected_group_id is None or selected_passenger_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Choose both a client group and passenger.",
            )
        group_stmt = select(ClientGroupModel).where(
            ClientGroupModel.id == selected_group_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.status.notin_({"archived", "deleted"}),
        )
        passenger_stmt = select(PassportSubmissionModel).where(
            PassportSubmissionModel.id == selected_passenger_id,
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == selected_group_id,
        )
        if current_user.role != UserRole.SUPER_ADMIN:
            group_stmt = AuthorizationPolicy.apply_group_visibility_scope(
                group_stmt,
                current_user,
            )
            passenger_stmt = AuthorizationPolicy.apply_passport_visibility_scope(
                passenger_stmt,
                current_user,
            )
        group = await session.scalar(group_stmt)
        passenger = await session.scalar(passenger_stmt)
        if group is None or passenger is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The selected group and passenger do not match.",
            )
        try:
            ingestion_result = await ingest_reviewed_artifact(
                session,
                review=review,
                group_id=selected_group_id,
                passenger_id=selected_passenger_id,
                created_by_user_id=current_user.id,
                actor_email=current_user.email,
            )
            created_storage_keys = list(ingestion_result.storage_keys)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from None
        review.selected_group_id = selected_group_id
        review.selected_passenger_id = selected_passenger_id
        review.status = "resolved"
        review.resolution_code = payload.action
        review.resolved_at = now
        result_message = (
            "The exact document was already present for this passenger; "
            "the duplicate was recorded without creating another copy."
            if ingestion_result.duplicate
            else "The email document was added to the passenger record."
        )
    elif payload.action == "mark_unrelated":
        await mark_message_unrelated(
            session,
            message=message,
            review=review,
            current_user=current_user,
            agency_id=agency_id,
            now=now,
        )
        result_message = "The email was marked as unrelated."
    elif payload.action == "reject":
        review.status = "rejected"
        review.resolution_code = "rejected"
        review.resolved_at = now
        if artifact is not None:
            artifact.processing_status = "ignored"
        result_message = "The proposed email action was rejected."
    elif payload.action == "defer":
        review.status = "deferred"
        review.resolution_code = "deferred"
        review.deferred_until = now + timedelta(days=1)
        result_message = "The review was deferred for 24 hours."
    else:
        if connection.status not in {"active", "failing"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Resume or reconnect the email account before retrying.",
            )
        review.status = "resolved"
        review.resolution_code = "retry_queued"
        review.resolved_at = now
        if artifact is not None:
            artifact.retrieval_status = "pending"
            artifact.processing_status = "pending"
            artifact.next_retry_at = now
        message.processing_status = "queued"
        connection.sync_state = "queued"
        connection.next_sync_at = now
        should_queue_retry = True
        result_message = "The email item was queued for another processing attempt."

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
