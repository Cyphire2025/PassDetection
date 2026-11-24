"""Distribution upload persistence scope."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentUploadChunkModel,
)
from app.infrastructure.documents.document_matcher import (
    DocumentMatcher,
    PassengerIdentifier,
)
from app.presentation.api.v1.document_chunk_uploads import (
    DocumentChunkMetadata,
    acquire_document_upload_advisory_lock,
    acquire_document_upload_scope_advisory_lock,
    resolve_concurrent_document_chunk_replay,
    validate_next_document_chunk,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _enforce_group_document_assignment_capacity,
    _first_blocking_processing_upload_id,
)
from app.presentation.api.v1.routes.document_distribution_replacements import (
    FilenameReplacement,
    apply_filename_replacements,
)
from app.presentation.api.v1.routes.document_distribution_review_support import (
    _LinkedDocumentMatchSource,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _lock_and_validate_document_match_scope,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _ConcurrentDocumentChunkReplay,
)


@dataclass(slots=True)
class DistributionUploadPersistence:
    """Shared scope and replacement state for the ingestion transaction hooks."""

    session: AsyncSession
    current_user: User
    group_id: uuid.UUID
    agency_id: uuid.UUID
    document_type: str
    matcher: DocumentMatcher
    roster_snapshot: tuple[tuple[str, ...], ...]
    linked_source: _LinkedDocumentMatchSource
    supplemental_identifiers: tuple[PassengerIdentifier, ...]
    chunk_metadata: DocumentChunkMetadata | None
    existing_batch: DocumentDistributionBatchModel | None
    fingerprint: str | None
    incoming_file_count: int
    chunk_byte_count: int
    replacement_decisions: dict[str, FilenameReplacement]
    replacement_actor_id: uuid.UUID
    replacement_actor_email: str | None
    replacement_cleanup_ids: list[uuid.UUID]

    async def reauthorize_before_persistence(self) -> tuple[uuid.UUID | None, str | None]:
        actor, _ = await _lock_and_validate_document_match_scope(
            self.session,
            current_user=self.current_user,
            group_id=self.group_id,
            agency_id=self.agency_id,
            matcher=self.matcher,
            expected_roster_snapshot=self.roster_snapshot,
            expected_source_snapshot=self.linked_source.snapshot,
            expected_supplemental_identifiers=self.supplemental_identifiers,
        )
        await acquire_document_upload_scope_advisory_lock(
            self.session,
            agency_id=self.agency_id,
            group_id=self.group_id,
            document_type=self.document_type,
        )
        # Use the same batch-before-document order as Save/Delete. This also
        # serializes replacement against document assignment and draft edits.
        await self.session.execute(
            select(DocumentDistributionBatchModel.id)
            .where(
                DocumentDistributionBatchModel.agency_id == self.agency_id,
                DocumentDistributionBatchModel.group_id == self.group_id,
                DocumentDistributionBatchModel.document_type == self.document_type,
            )
            .order_by(DocumentDistributionBatchModel.id)
            .with_for_update()
        )
        if self.chunk_metadata is not None:
            await acquire_document_upload_advisory_lock(
                self.session,
                workflow="distribution",
                upload_id=self.chunk_metadata.upload_id,
            )
            serialized_batch_result = await self.session.execute(
                select(DocumentDistributionBatchModel)
                .where(DocumentDistributionBatchModel.id == self.chunk_metadata.upload_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            serialized_batch = serialized_batch_result.scalar_one_or_none()
            if serialized_batch is not None and (
                serialized_batch.agency_id != self.agency_id
                or serialized_batch.group_id != self.group_id
                or serialized_batch.document_type != self.document_type
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is not available to this group",
                )
            if (
                self.chunk_metadata.chunk_index == 0
                and serialized_batch is None
                and await _first_blocking_processing_upload_id(
                    self.session,
                    group_id=self.group_id,
                    agency_id=self.agency_id,
                    document_type=self.document_type,
                    exclude_upload_id=self.chunk_metadata.upload_id,
                    lock=True,
                )
                is not None
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Discard or resume the existing incomplete upload before "
                        "starting another one"
                    ),
                )
            locked_receipts_result = await self.session.execute(
                select(DocumentUploadChunkModel)
                .where(
                    DocumentUploadChunkModel.upload_id == self.chunk_metadata.upload_id,
                    DocumentUploadChunkModel.workflow == "distribution",
                )
                .order_by(DocumentUploadChunkModel.chunk_index.asc())
                .with_for_update()
            )
            locked_receipts = list(locked_receipts_result.scalars().all())
            assert self.fingerprint is not None
            if (
                resolve_concurrent_document_chunk_replay(
                    locked_receipts,
                    metadata=self.chunk_metadata,
                    agency_id=self.agency_id,
                    workflow="distribution",
                    group_id=self.group_id,
                    document_type=self.document_type,
                    fingerprint=self.fingerprint,
                    file_count=self.incoming_file_count,
                    byte_count=self.chunk_byte_count,
                )
                is not None
            ):
                raise _ConcurrentDocumentChunkReplay
            if serialized_batch is not None and self.existing_batch is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is incomplete and requires administrator review",
                )
            if serialized_batch is None and self.existing_batch is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is no longer available",
                )
            if serialized_batch is not None and serialized_batch.status != "processing":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "This upload was completed or closed while the PDFs were being processed. "
                        "Check the remaining PDFs in a new upload."
                    ),
                )
            validate_next_document_chunk(
                locked_receipts,
                metadata=self.chunk_metadata,
                incoming_file_count=self.incoming_file_count,
                incoming_byte_count=self.chunk_byte_count,
            )
        self.replacement_actor_id = actor.id
        self.replacement_actor_email = actor.email
        return actor.id, actor.email

    async def enforce_capacity_before_persistence(self, incoming_rows: int) -> None:
        await _enforce_group_document_assignment_capacity(
            self.session,
            group_id=self.group_id,
            agency_id=self.agency_id,
            document_type=self.document_type,
            incoming_rows=incoming_rows,
        )

    async def replace_successfully_stored_documents(
        self,
        documents: list[DistributedDocumentModel],
    ) -> None:
        self.replacement_cleanup_ids.extend(
            await apply_filename_replacements(
                self.session,
                agency_id=self.agency_id,
                group_id=self.group_id,
                document_type=self.document_type,
                new_documents=documents,
                replacements=self.replacement_decisions,
                actor_id=self.replacement_actor_id,
                actor_email=self.replacement_actor_email,
            )
        )
