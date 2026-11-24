"""Validated review actions; the route owns audit, commit and retry publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.email.review_decisions import mark_message_unrelated
from app.infrastructure.email.sync_service import ingest_reviewed_artifact
from app.presentation.api.v1.routes.email_review_context import LockedEmailReview
from app.presentation.api.v1.schemas.email_integration_schemas import ResolveEmailReviewRequest


@dataclass(frozen=True, slots=True)
class EmailReviewActionOutcome:
    should_queue_retry: bool
    created_storage_keys: list[str]
    result_message: str


async def _apply_email_review_action(
    session: AsyncSession,
    *,
    locked: LockedEmailReview,
    payload: ResolveEmailReviewRequest,
    current_user: User,
    now: datetime,
) -> EmailReviewActionOutcome:
    """Apply one allowed decision to the exact locked ORM rows without committing."""
    connection = locked.connection
    message = locked.message
    artifact = locked.artifact
    review = locked.review
    agency_id = locked.agency_id
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
    return EmailReviewActionOutcome(
        should_queue_retry=should_queue_retry,
        created_storage_keys=created_storage_keys,
        result_message=result_message,
    )
