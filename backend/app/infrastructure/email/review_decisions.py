"""Durable effects of marking an email unrelated within the caller's transaction."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import (
    EmailArtifactModel,
    EmailMessageModel,
    EmailReviewItemModel,
)


async def mark_message_unrelated(
    session: AsyncSession,
    *,
    message: EmailMessageModel,
    review: EmailReviewItemModel,
    current_user: User,
    agency_id: uuid.UUID,
    now: datetime,
) -> None:
    """Cancel only this owner's derived work; the locked route commits/audits it."""
    review.status = "resolved"
    review.resolution_code = "marked_unrelated"
    review.resolved_at = now
    message.relevance_status = "ignored"
    message.processing_status = "ignored"
    evidence = dict(message.evidence_json or {})
    evidence["human_marked_unrelated"] = True
    evidence["human_marked_unrelated_at"] = now.isoformat()
    evidence["human_marked_unrelated_by"] = str(current_user.id)
    message.evidence_json = evidence
    await session.execute(
        update(EmailAiAnalysisModel)
        .where(
            EmailAiAnalysisModel.message_id == message.id,
            EmailAiAnalysisModel.connection_id == message.connection_id,
            EmailAiAnalysisModel.agency_id == agency_id,
            EmailAiAnalysisModel.owner_user_id == current_user.id,
            EmailAiAnalysisModel.status.in_(
                {
                    "pending",
                    "processing",
                    "completed",
                    "review_required",
                    "failed",
                }
            ),
        )
        .values(
            status="ignored",
            needs_attention=False,
            lease_token=None,
            lease_expires_at=None,
            next_attempt_at=None,
            completed_at=now,
            last_error_code="human_marked_unrelated",
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(EmailActionProposalModel)
        .where(
            EmailActionProposalModel.message_id == message.id,
            EmailActionProposalModel.agency_id == agency_id,
            EmailActionProposalModel.owner_user_id == current_user.id,
            EmailActionProposalModel.status.in_({"proposed", "approval_required", "blocked"}),
        )
        .values(
            status="dismissed",
            decision_by_user_id=current_user.id,
            decision_at=now,
            decision_note="Source email marked unrelated by its owner.",
            revision=EmailActionProposalModel.revision + 1,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(EmailDetectedDeadlineModel)
        .where(
            EmailDetectedDeadlineModel.message_id == message.id,
            EmailDetectedDeadlineModel.agency_id == agency_id,
            EmailDetectedDeadlineModel.owner_user_id == current_user.id,
            EmailDetectedDeadlineModel.status.in_({"detected", "review_required", "acknowledged"}),
        )
        .values(status="dismissed", updated_at=now)
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(EmailReplyDraftModel)
        .where(
            EmailReplyDraftModel.message_id == message.id,
            EmailReplyDraftModel.agency_id == agency_id,
            EmailReplyDraftModel.owner_user_id == current_user.id,
            EmailReplyDraftModel.status.in_({"prepared", "edited", "approved"}),
        )
        .values(
            status="dismissed",
            revision=EmailReplyDraftModel.revision + 1,
            edited_by_user_id=current_user.id,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    related_artifacts = list(
        (
            await session.execute(
                select(EmailArtifactModel)
                .where(
                    EmailArtifactModel.message_id == message.id,
                    EmailArtifactModel.owner_user_id == current_user.id,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for related_artifact in related_artifacts:
        related_artifact.processing_status = "ignored"
        related_artifact.updated_at = now
    sibling_reviews = list(
        (
            await session.execute(
                select(EmailReviewItemModel)
                .where(
                    EmailReviewItemModel.message_id == message.id,
                    EmailReviewItemModel.owner_user_id == current_user.id,
                    EmailReviewItemModel.id != review.id,
                    EmailReviewItemModel.status.in_({"open", "deferred"}),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for sibling in sibling_reviews:
        sibling.status = "cancelled"
        sibling.resolution_code = "message_marked_unrelated"
        sibling.resolved_by_user_id = current_user.id
        sibling.resolved_at = now
        sibling.revision += 1
        sibling.updated_at = now
