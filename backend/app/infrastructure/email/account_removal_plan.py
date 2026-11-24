"""Typed attributable-record collection for one owner-scoped mailbox removal."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.email_models import (
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import DistributedDocumentModel


@dataclass(frozen=True)
class EmailAccountRemovalPlan:
    """Immutable IDs and candidate object keys selected inside the caller transaction."""

    connection_id: uuid.UUID
    agency_id: uuid.UUID
    owner_user_id: uuid.UUID
    message_ids: tuple[uuid.UUID, ...]
    artifact_ids: tuple[uuid.UUID, ...]
    artifact_storage_keys: tuple[str, ...]
    review_ids: tuple[uuid.UUID, ...]
    analysis_ids: tuple[uuid.UUID, ...]
    removable_document_ids: tuple[uuid.UUID, ...]
    document_storage_keys: tuple[str, ...]
    batch_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class EmailAccountRemovalCounts:
    """Actual relational delete totals returned to the public result owner."""

    notification_count: int
    activity_count: int
    audit_log_count: int


async def _collect_email_account_removal_plan(
    session: AsyncSession, *, connection: EmailConnectionModel
) -> EmailAccountRemovalPlan:
    """Select only attributable records and documents that no other artifact references."""

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
    return EmailAccountRemovalPlan(
        connection_id=connection_id,
        agency_id=agency_id,
        owner_user_id=owner_user_id,
        message_ids=message_ids,
        artifact_ids=artifact_ids,
        artifact_storage_keys=artifact_storage_keys,
        review_ids=review_ids,
        analysis_ids=analysis_ids,
        removable_document_ids=removable_document_ids,
        document_storage_keys=document_storage_keys,
        batch_ids=batch_ids,
    )
