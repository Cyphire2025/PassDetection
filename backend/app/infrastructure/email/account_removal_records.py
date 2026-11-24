"""Ordered relational email-account deletion inside a caller-owned transaction."""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailAiFeedbackModel,
    EmailAiRolloutPolicyModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailOAuthStateModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
    NotificationModel,
)

from .account_removal_plan import EmailAccountRemovalCounts, EmailAccountRemovalPlan


async def _delete_email_account_records(
    session: AsyncSession, *, connection: EmailConnectionModel, plan: EmailAccountRemovalPlan
) -> EmailAccountRemovalCounts:
    """Retain foreign-key-safe delete order and the original explicit flush boundary."""

    connection_id = plan.connection_id
    agency_id = plan.agency_id
    owner_user_id = plan.owner_user_id
    message_ids = plan.message_ids
    artifact_ids = plan.artifact_ids
    review_ids = plan.review_ids
    analysis_ids = plan.analysis_ids
    removable_document_ids = plan.removable_document_ids
    batch_ids = plan.batch_ids

    notification_count = 0
    if message_ids:
        notification_delete = await session.execute(
            delete(NotificationModel).where(
                NotificationModel.agency_id == agency_id,
                NotificationModel.user_id == owner_user_id,
                NotificationModel.category == "email_operations",
                NotificationModel.entity_type == "email_message",
                NotificationModel.entity_id.in_(tuple(str(item) for item in message_ids)),
            )
        )
        notification_count = notification_delete.rowcount or 0

    # Security audit entries are historical snapshots, not owned email content.
    # Their PII-bounded identifiers remain after the connection is removed and
    # schema 0087 prevents ordinary application DELETE/UPDATE operations.
    audit_log_count = 0

    if analysis_ids:
        await session.execute(
            delete(EmailAiFeedbackModel).where(EmailAiFeedbackModel.analysis_id.in_(analysis_ids))
        )
        await session.execute(
            delete(EmailReplyDraftModel).where(EmailReplyDraftModel.analysis_id.in_(analysis_ids))
        )
        await session.execute(
            delete(EmailActionProposalModel).where(
                EmailActionProposalModel.analysis_id.in_(analysis_ids)
            )
        )
        await session.execute(
            delete(EmailDetectedDeadlineModel).where(
                EmailDetectedDeadlineModel.analysis_id.in_(analysis_ids)
            )
        )
        await session.execute(
            delete(EmailAiAnalysisModel).where(EmailAiAnalysisModel.id.in_(analysis_ids))
        )

    activity_delete = await session.execute(
        delete(EmailActivityEventModel).where(
            EmailActivityEventModel.connection_id == connection_id,
            EmailActivityEventModel.agency_id == agency_id,
            EmailActivityEventModel.owner_user_id == owner_user_id,
        )
    )
    activity_count = activity_delete.rowcount or 0

    if review_ids:
        await session.execute(
            delete(EmailReviewItemModel).where(EmailReviewItemModel.id.in_(review_ids))
        )
    if artifact_ids:
        await session.execute(
            delete(EmailArtifactDocumentModel).where(
                EmailArtifactDocumentModel.artifact_id.in_(artifact_ids)
            )
        )
        # Cross-message duplicate pointers are metadata only.  Clear pointers
        # to artifacts being removed so another connected mailbox is preserved.
        await session.execute(
            update(EmailArtifactModel)
            .where(EmailArtifactModel.duplicate_of_id.in_(artifact_ids))
            .values(duplicate_of_id=None)
        )
        await session.execute(
            delete(EmailArtifactModel).where(EmailArtifactModel.id.in_(artifact_ids))
        )
    if message_ids:
        await session.execute(
            delete(EmailMessageModel).where(EmailMessageModel.id.in_(message_ids))
        )

    await session.execute(
        delete(EmailOAuthStateModel).where(
            EmailOAuthStateModel.connection_id == connection_id,
            EmailOAuthStateModel.agency_id == agency_id,
            EmailOAuthStateModel.user_id == owner_user_id,
        )
    )
    await session.execute(
        delete(EmailAiRolloutPolicyModel).where(
            EmailAiRolloutPolicyModel.scope_type == "connection",
            EmailAiRolloutPolicyModel.connection_id == connection_id,
            EmailAiRolloutPolicyModel.agency_id == agency_id,
            EmailAiRolloutPolicyModel.owner_user_id == owner_user_id,
        )
    )

    if removable_document_ids:
        await session.execute(
            delete(DocumentWhatsAppDeliveryModel).where(
                DocumentWhatsAppDeliveryModel.distributed_document_id.in_(removable_document_ids),
                DocumentWhatsAppDeliveryModel.agency_id == agency_id,
            )
        )
        await session.execute(
            delete(DistributedDocumentModel).where(
                DistributedDocumentModel.id.in_(removable_document_ids),
                DistributedDocumentModel.agency_id == agency_id,
            )
        )
    if batch_ids:
        remaining_batch_ids = set(
            (
                await session.scalars(
                    select(DistributedDocumentModel.batch_id).where(
                        DistributedDocumentModel.batch_id.in_(batch_ids)
                    )
                )
            ).all()
        )
        empty_batch_ids = tuple(set(batch_ids) - remaining_batch_ids)
        if empty_batch_ids:
            await session.execute(
                update(DocumentWhatsAppDeliveryModel)
                .where(DocumentWhatsAppDeliveryModel.document_batch_id.in_(empty_batch_ids))
                .values(document_batch_id=None)
            )
            await session.execute(
                delete(DocumentDistributionBatchModel).where(
                    DocumentDistributionBatchModel.id.in_(empty_batch_ids),
                    DocumentDistributionBatchModel.agency_id == agency_id,
                )
            )

    await session.delete(connection)
    await session.flush()
    return EmailAccountRemovalCounts(
        notification_count=notification_count,
        activity_count=activity_count,
        audit_log_count=audit_log_count,
    )
