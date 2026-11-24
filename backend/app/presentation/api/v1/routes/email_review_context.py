"""Current-owner email review lookup, ordered row locks and decision validation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.email_models import (
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.presentation.api.v1.routes.email_integration_access import (
    _ACTIVE_REVIEW_STATUSES,
    _email_owner_filters,
    _owned_connection,
)
from app.presentation.api.v1.routes.email_integration_review_support import _allowed_review_actions
from app.presentation.api.v1.schemas.email_integration_schemas import ResolveEmailReviewRequest


@dataclass(frozen=True, slots=True)
class LockedEmailReview:
    connection: EmailConnectionModel
    message: EmailMessageModel
    artifact: EmailArtifactModel | None
    review: EmailReviewItemModel
    agency_id: uuid.UUID


async def _lock_email_review(
    session: AsyncSession,
    *,
    review_id: uuid.UUID,
    payload: ResolveEmailReviewRequest,
    current_user: User,
) -> LockedEmailReview:
    """Resolve and validate the same personal mailbox under worker-matching locks."""
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
    return LockedEmailReview(
        connection=connection,
        message=message,
        artifact=artifact,
        review=review,
        agency_id=agency_id,
    )
