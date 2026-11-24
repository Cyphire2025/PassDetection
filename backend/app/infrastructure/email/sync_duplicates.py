"""Durable email synchronization: duplicates."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.infrastructure.database.email_models import (
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailMessageModel,
)
from app.infrastructure.database.models import DistributedDocumentModel

from .sync_contracts import SyncClaim
from .sync_events import _record_event


def _is_reusable_duplicate_document(document: DistributedDocumentModel) -> bool:
    """Return whether an exact-content duplicate still has a live assignment."""

    return document.passenger_id is not None and document.match_status == "matched"


def _live_duplicate_documents_statement(
    *,
    agency_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    artifact_id: uuid.UUID,
    sha256_digest: str,
) -> Select[tuple[EmailArtifactModel, DistributedDocumentModel]]:
    """Select exact email duplicates whose passenger documents still exist."""

    return (
        select(EmailArtifactModel, DistributedDocumentModel)
        .join(
            EmailArtifactDocumentModel,
            EmailArtifactDocumentModel.artifact_id == EmailArtifactModel.id,
        )
        .join(
            DistributedDocumentModel,
            DistributedDocumentModel.id == EmailArtifactDocumentModel.distributed_document_id,
        )
        .where(
            EmailArtifactModel.agency_id == agency_id,
            EmailArtifactModel.owner_user_id == owner_user_id,
            EmailArtifactModel.sha256_digest == sha256_digest,
            EmailArtifactModel.id != artifact_id,
            EmailArtifactModel.processing_status.in_({"completed", "duplicate"}),
            EmailArtifactDocumentModel.agency_id == agency_id,
            EmailArtifactDocumentModel.owner_user_id == owner_user_id,
            DistributedDocumentModel.agency_id == agency_id,
            DistributedDocumentModel.passenger_id.is_not(None),
            DistributedDocumentModel.match_status == "matched",
        )
        .order_by(
            EmailArtifactModel.created_at.asc(),
            DistributedDocumentModel.created_at.asc(),
        )
        .with_for_update(of=DistributedDocumentModel)
    )


async def _reuse_live_duplicate_assignments(
    session: AsyncSession,
    *,
    claim: SyncClaim,
    message: EmailMessageModel,
    artifact: EmailArtifactModel,
    duplicate_rows: list[tuple[EmailArtifactModel, DistributedDocumentModel]],
    processed_at: datetime,
) -> None:
    """Link a new email artifact to its still-active canonical documents."""

    source_artifact = duplicate_rows[0][0]
    documents = list(
        {
            document.id: document
            for _, document in duplicate_rows
            if _is_reusable_duplicate_document(document)
        }.values()
    )
    if not documents:
        raise ValueError("A reusable duplicate requires an active passenger document")

    group_ids = {document.group_id for document in documents}
    passenger_ids = {
        document.passenger_id for document in documents if document.passenger_id is not None
    }
    document_types = {document.document_type for document in documents}
    artifact.duplicate_of_id = source_artifact.id
    artifact.group_id = next(iter(group_ids)) if len(group_ids) == 1 else None
    artifact.passenger_id = next(iter(passenger_ids)) if len(passenger_ids) == 1 else None
    artifact.detected_type = (
        next(iter(document_types)) if len(document_types) == 1 else source_artifact.detected_type
    )
    artifact.match_confidence = min(document.match_confidence for document in documents)
    artifact.processing_status = "duplicate"
    artifact.processed_at = processed_at
    artifact.error_code = None
    artifact.error_message = None

    for document in documents:
        session.add(
            EmailArtifactDocumentModel(
                id=uuid.uuid4(),
                agency_id=claim.agency_id,
                owner_user_id=claim.owner_user_id,
                artifact_id=artifact.id,
                distributed_document_id=document.id,
                result_type="existing_duplicate",
                match_confidence=document.match_confidence,
                match_evidence={
                    "source": "email_integration",
                    "exact_content_duplicate": True,
                    "existing_assignment_reused": True,
                },
                created_at=processed_at,
            )
        )

    if len(group_ids) == 1:
        duplicate_group_id = next(iter(group_ids))
        message.group_id = (
            duplicate_group_id if message.group_id in {None, duplicate_group_id} else None
        )
    else:
        message.group_id = None

    stored_evidence = message.evidence_json if isinstance(message.evidence_json, dict) else {}
    stored_signals = stored_evidence.get("signals", [])
    existing_signals = (
        [item for item in stored_signals if isinstance(item, str)]
        if isinstance(stored_signals, list)
        else []
    )
    message.relevance_status = "relevant"
    message.relevance_confidence = max(message.relevance_confidence or 0.0, 0.94)
    message.evidence_json = {
        "signals": list(
            dict.fromkeys(
                [
                    *existing_signals,
                    "exact_content_duplicate",
                    "existing_document_assignment",
                ]
            )
        )
    }

    await _record_event(
        session,
        connection_id=claim.connection_id,
        agency_id=claim.agency_id,
        owner_user_id=claim.owner_user_id,
        message_id=message.id,
        artifact_id=artifact.id,
        event_type="artifact_duplicate_reused",
        stage="success",
        summary_code="EMAIL_ARTIFACT_DUPLICATE_REUSED",
        details={"document_count": len(documents)},
        confidence=artifact.match_confidence,
        changed_entity_type=("passport_submission" if artifact.passenger_id is not None else None),
        changed_entity_id=artifact.passenger_id,
    )
