"""Transactional cleanup for one owner-scoped email connection.

The connection row is the deletion boundary.  This module deliberately removes
only records that can be traced to that connection and only travel documents
that were created by its artifacts and are not referenced by another email
artifact.  Manually uploaded documents and documents reused as duplicates are
preserved.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

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


@dataclass(frozen=True)
class EmailAccountRemovalResult:
    """Database cleanup totals and now-unreferenced object-storage keys."""

    connection_id: uuid.UUID
    message_count: int
    artifact_count: int
    review_count: int
    activity_count: int
    document_count: int
    notification_count: int
    audit_log_count: int
    storage_keys: tuple[str, ...]


async def purge_email_connection_records(
    session: AsyncSession,
    *,
    connection: EmailConnectionModel,
) -> EmailAccountRemovalResult:
    """Remove the selected connection's durable records inside one transaction.

    The caller owns the transaction and must commit before deleting the returned
    object-storage keys.  That ordering avoids leaving live database rows that
    point at missing files when a relational delete fails.
    """

    connection_id = connection.id
    agency_id = connection.agency_id
    owner_user_id = connection.owner_user_id

    message_ids = tuple(
        (
            await session.scalars(
                select(EmailMessageModel.id).where(
                    EmailMessageModel.connection_id == connection_id,
                    EmailMessageModel.agency_id == agency_id,
                    EmailMessageModel.owner_user_id == owner_user_id,
                )
            )
        ).all()
    )
    artifact_ids: tuple[uuid.UUID, ...] = ()
    artifact_storage_keys: tuple[str, ...] = ()
    review_ids: tuple[uuid.UUID, ...] = ()
    analysis_ids: tuple[uuid.UUID, ...] = ()

    if message_ids:
        artifact_rows = (
            await session.execute(
                select(EmailArtifactModel.id, EmailArtifactModel.storage_key).where(
                    EmailArtifactModel.message_id.in_(message_ids),
                    EmailArtifactModel.agency_id == agency_id,
                    EmailArtifactModel.owner_user_id == owner_user_id,
                )
            )
        ).all()
        artifact_ids = tuple(row.id for row in artifact_rows)
        artifact_storage_keys = tuple(row.storage_key for row in artifact_rows if row.storage_key)
        review_ids = tuple(
            (
                await session.scalars(
                    select(EmailReviewItemModel.id).where(
                        EmailReviewItemModel.message_id.in_(message_ids),
                        EmailReviewItemModel.agency_id == agency_id,
                        EmailReviewItemModel.owner_user_id == owner_user_id,
                    )
                )
            ).all()
        )
        analysis_ids = tuple(
            (
                await session.scalars(
                    select(EmailAiAnalysisModel.id).where(
                        EmailAiAnalysisModel.message_id.in_(message_ids),
                        EmailAiAnalysisModel.connection_id == connection_id,
                        EmailAiAnalysisModel.agency_id == agency_id,
                        EmailAiAnalysisModel.owner_user_id == owner_user_id,
                    )
                )
            ).all()
        )

    removable_document_ids: tuple[uuid.UUID, ...] = ()
    document_storage_keys: tuple[str, ...] = ()
    batch_ids: tuple[uuid.UUID, ...] = ()
    if artifact_ids:
        created_document_ids = set(
            (
                await session.scalars(
                    select(EmailArtifactDocumentModel.distributed_document_id).where(
                        EmailArtifactDocumentModel.artifact_id.in_(artifact_ids),
                        EmailArtifactDocumentModel.agency_id == agency_id,
                        EmailArtifactDocumentModel.owner_user_id == owner_user_id,
                        EmailArtifactDocumentModel.result_type == "created",
                    )
                )
            ).all()
        )
        if created_document_ids:
            externally_referenced_ids = set(
                (
                    await session.scalars(
                        select(EmailArtifactDocumentModel.distributed_document_id).where(
                            EmailArtifactDocumentModel.distributed_document_id.in_(
                                created_document_ids
                            ),
                            EmailArtifactDocumentModel.artifact_id.not_in(artifact_ids),
                        )
                    )
                ).all()
            )
            removable_document_ids = tuple(
                sorted(created_document_ids - externally_referenced_ids, key=str)
            )

    if removable_document_ids:
        document_rows = (
            await session.execute(
                select(
                    DistributedDocumentModel.id,
                    DistributedDocumentModel.batch_id,
                    DistributedDocumentModel.storage_key,
                ).where(
                    DistributedDocumentModel.id.in_(removable_document_ids),
                    DistributedDocumentModel.agency_id == agency_id,
                )
            )
        ).all()
        removable_document_ids = tuple(row.id for row in document_rows)
        batch_ids = tuple(dict.fromkeys(row.batch_id for row in document_rows))
        document_storage_keys = tuple(row.storage_key for row in document_rows if row.storage_key)

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

    candidate_storage_keys = tuple(dict.fromkeys((*artifact_storage_keys, *document_storage_keys)))
    storage_keys: tuple[str, ...] = ()
    if candidate_storage_keys:
        remaining_artifact_keys = set(
            (
                await session.scalars(
                    select(EmailArtifactModel.storage_key).where(
                        EmailArtifactModel.storage_key.in_(candidate_storage_keys)
                    )
                )
            ).all()
        )
        remaining_document_keys = set(
            (
                await session.scalars(
                    select(DistributedDocumentModel.storage_key).where(
                        DistributedDocumentModel.storage_key.in_(candidate_storage_keys)
                    )
                )
            ).all()
        )
        referenced_keys = remaining_artifact_keys | remaining_document_keys
        storage_keys = tuple(key for key in candidate_storage_keys if key not in referenced_keys)

    return EmailAccountRemovalResult(
        connection_id=connection_id,
        message_count=len(message_ids),
        artifact_count=len(artifact_ids),
        review_count=len(review_ids),
        activity_count=activity_count,
        document_count=len(removable_document_ids),
        notification_count=notification_count,
        audit_log_count=audit_log_count,
        storage_keys=storage_keys,
    )
