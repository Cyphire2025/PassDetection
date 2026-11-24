"""Durable email synchronization: review ingestion."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.infrastructure.database.email_models import (
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.models import DistributedDocumentModel
from app.infrastructure.email.pdf_validator import EmailPdfValidationError
from app.infrastructure.storage.minio_repository import MinioStorageRepository

from .sync_attachments import _validate_untrusted_email_pdf
from .sync_contracts import _SUPPORTED_PDF_TYPES, ReviewedArtifactIngestionResult, SyncClaim
from .sync_document_ingestion import _ingest_confirmed_artifact
from .sync_events import _advisory_transaction_lock, _record_event, _refresh_message_counts


async def ingest_reviewed_artifact(
    session: AsyncSession,
    *,
    review: EmailReviewItemModel,
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    actor_email: str,
) -> ReviewedArtifactIngestionResult:
    """Route a staff-confirmed staged PDF through the shared document pipeline."""

    if created_by_user_id != review.owner_user_id:
        raise ValueError("The reviewed email artifact belongs to another user")
    result = await session.execute(
        select(EmailArtifactModel, EmailMessageModel, EmailConnectionModel)
        .join(
            EmailMessageModel,
            (
                (EmailMessageModel.id == EmailArtifactModel.message_id)
                & (EmailMessageModel.owner_user_id == EmailArtifactModel.owner_user_id)
            ),
        )
        .join(
            EmailConnectionModel,
            (
                (EmailConnectionModel.id == EmailMessageModel.connection_id)
                & (EmailConnectionModel.owner_user_id == EmailMessageModel.owner_user_id)
            ),
        )
        .where(
            EmailArtifactModel.id == review.artifact_id,
            EmailArtifactModel.agency_id == review.agency_id,
            EmailArtifactModel.owner_user_id == review.owner_user_id,
            EmailMessageModel.id == review.message_id,
            EmailMessageModel.owner_user_id == review.owner_user_id,
            EmailConnectionModel.owner_user_id == review.owner_user_id,
        )
        .with_for_update(of=EmailArtifactModel)
    )
    row = result.one_or_none()
    if row is None:
        raise ValueError("The reviewed email artifact is no longer available")
    artifact, message, connection = row
    if not artifact.storage_key:
        raise ValueError("The reviewed email document is not available in storage")
    if artifact.detected_type not in _SUPPORTED_PDF_TYPES:
        raise ValueError("Choose a supported visa or flight ticket PDF")

    storage = MinioStorageRepository()
    content = await storage.get_file(artifact.storage_key)
    try:
        validated = await _validate_untrusted_email_pdf(
            content=content,
            filename=artifact.filename,
            declared_content_type=artifact.verified_content_type,
            settings=get_settings(),
            agency_id=review.agency_id,
            user_id=review.owner_user_id,
        )
    except EmailPdfValidationError:
        raise ValueError("The reviewed email document failed security validation") from None
    artifact.sha256_digest = validated.sha256_hex
    artifact.verified_content_type = validated.content_type
    artifact.size_bytes = len(validated.content)
    await _advisory_transaction_lock(
        session,
        f"email-content:{review.agency_id}:{validated.sha256_hex}",
    )
    await _advisory_transaction_lock(
        session,
        (f"email-document:{review.agency_id}:{group_id}:{passenger_id}:{artifact.detected_type}"),
    )

    duplicate_result = await session.execute(
        select(
            EmailArtifactModel.id,
            EmailArtifactDocumentModel.distributed_document_id,
        )
        .join(
            EmailArtifactDocumentModel,
            EmailArtifactDocumentModel.artifact_id == EmailArtifactModel.id,
        )
        .join(
            DistributedDocumentModel,
            DistributedDocumentModel.id == EmailArtifactDocumentModel.distributed_document_id,
        )
        .where(
            EmailArtifactModel.agency_id == review.agency_id,
            EmailArtifactModel.owner_user_id == review.owner_user_id,
            EmailArtifactModel.sha256_digest == validated.sha256_hex,
            EmailArtifactModel.id != artifact.id,
            EmailArtifactModel.processing_status.in_({"completed", "duplicate"}),
            DistributedDocumentModel.agency_id == review.agency_id,
            EmailArtifactDocumentModel.owner_user_id == review.owner_user_id,
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.passenger_id == passenger_id,
            DistributedDocumentModel.document_type == artifact.detected_type,
        )
        .order_by(EmailArtifactModel.created_at.asc())
    )
    duplicate_rows = list(duplicate_result.all())
    if duplicate_rows:
        duplicate_artifact_id = duplicate_rows[0][0]
        document_ids = tuple(dict.fromkeys(row[1] for row in duplicate_rows))
        linked_ids = set(
            (
                await session.execute(
                    select(EmailArtifactDocumentModel.distributed_document_id).where(
                        EmailArtifactDocumentModel.artifact_id == artifact.id,
                        EmailArtifactDocumentModel.owner_user_id == review.owner_user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for document_id in document_ids:
            if document_id in linked_ids:
                continue
            session.add(
                EmailArtifactDocumentModel(
                    id=uuid.uuid4(),
                    agency_id=review.agency_id,
                    owner_user_id=review.owner_user_id,
                    artifact_id=artifact.id,
                    distributed_document_id=document_id,
                    result_type="existing_duplicate",
                    match_confidence=artifact.match_confidence,
                    match_evidence={
                        "source": "email_integration",
                        "human_confirmed": True,
                        "exact_content_duplicate": True,
                    },
                    created_at=datetime.now(tz=UTC),
                )
            )
        artifact.duplicate_of_id = duplicate_artifact_id
        artifact.group_id = group_id
        artifact.passenger_id = passenger_id
        artifact.processing_status = "duplicate"
        artifact.processed_at = datetime.now(tz=UTC)
        message.group_id = group_id
        await _record_event(
            session,
            connection_id=connection.id,
            agency_id=review.agency_id,
            owner_user_id=review.owner_user_id,
            message_id=message.id,
            artifact_id=artifact.id,
            event_type="artifact_deduplicated",
            stage="success",
            summary_code="EMAIL_ARTIFACT_DEDUPLICATED",
            details={"human_confirmed": True},
            actor_type="user",
            actor_user_id=created_by_user_id,
        )
        await _refresh_message_counts(session, message)
        return ReviewedArtifactIngestionResult(
            document_ids=document_ids,
            storage_keys=(),
            duplicate=True,
        )

    canonical_keys = await _ingest_confirmed_artifact(
        session,
        claim=SyncClaim(
            connection_id=connection.id,
            agency_id=review.agency_id,
            owner_user_id=review.owner_user_id,
            provider=connection.provider,
            provider_account_id=connection.provider_account_id,
            lease_token="human-review",
            generation=connection.sync_generation,
            access_token="",
            refresh_token=None,
            token_expires_at=None,
            sync_cursor=None,
        ),
        message=message,
        artifact=artifact,
        validated=validated,
        document_type=artifact.detected_type,
        group_id=group_id,
        passenger_id=passenger_id,
        created_by_user_id=created_by_user_id,
        actor_email=actor_email,
        result_type="created",
    )
    try:
        artifact.group_id = group_id
        artifact.passenger_id = passenger_id
        artifact.processing_status = "completed"
        artifact.processed_at = datetime.now(tz=UTC)
        message.group_id = group_id
        await _refresh_message_counts(session, message)
        document_ids_result = await session.execute(
            select(EmailArtifactDocumentModel.distributed_document_id).where(
                EmailArtifactDocumentModel.artifact_id == artifact.id,
                EmailArtifactDocumentModel.owner_user_id == review.owner_user_id,
            )
        )
    except Exception:
        await MinioStorageRepository().delete_files(canonical_keys)
        raise
    return ReviewedArtifactIngestionResult(
        document_ids=tuple(document_ids_result.scalars().all()),
        storage_keys=tuple(canonical_keys),
        duplicate=False,
    )
