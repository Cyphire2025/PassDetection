"""Distribution upload workflow."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    DocumentDistributionBatchModel,
)
from app.infrastructure.documents.distribution_capacity import DocumentDistributionCapacityError
from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentIngestionService,
)
from app.infrastructure.documents.document_matcher import (
    DocumentParserUnavailableError,
    UnsupportedDocumentBatchFormatError,
)
from app.infrastructure.documents.pdf_parser_sandbox import bounded_pdf_batch_timeout_seconds
from app.infrastructure.documents.storage_transfers import finish_cleanup_despite_cancellation
from app.infrastructure.documents.verification_staging import (
    validate_verification_receipt_token_batch,
)
from app.presentation.api.v1.document_chunk_uploads import (
    resolve_document_chunk_metadata,
    validate_document_chunk_size,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _all_group_documents,
)
from app.presentation.api.v1.routes.document_distribution_replacements import (
    parse_filename_replacements,
    replacement_chunk_fingerprint,
)
from app.presentation.api.v1.routes.document_distribution_responses import _batch_response
from app.presentation.api.v1.routes.document_distribution_scope import (
    _detach_distribution_batch_before_long_processing,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_match_roster_snapshot,
    _processing_batch_response,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _cleanup_remembered_request_staging,
    _ConcurrentDocumentChunkReplay,
)
from app.presentation.api.v1.routes.document_distribution_upload_chunk_state import (
    read_distribution_upload_chunk,
)
from app.presentation.api.v1.routes.document_distribution_upload_commit import (
    commit_distribution_upload,
)
from app.presentation.api.v1.routes.document_distribution_upload_content import (
    prepare_distribution_upload_content,
)
from app.presentation.api.v1.routes.document_distribution_upload_inputs import (
    validate_staging_receipt_batch as validate_staging_receipt_batch,
)
from app.presentation.api.v1.routes.document_distribution_upload_inputs import (
    validated_distribution_upload_inputs as validated_distribution_upload_inputs,
)
from app.presentation.api.v1.routes.document_distribution_upload_match_scope import (
    authorize_distribution_upload,
)
from app.presentation.api.v1.routes.document_distribution_upload_persistence_scope import (
    DistributionUploadPersistence,
)
from app.presentation.api.v1.routes.document_distribution_upload_response import (
    completed_distribution_upload_response,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentBatchResponse,
)


async def run_distribution_upload(
    *,
    group_id: uuid.UUID,
    document_type: str,
    files: list[UploadFile] | None,
    staging_receipts: list[str] | None,
    upload_id: uuid.UUID | None,
    chunk_id: uuid.UUID | None,
    chunk_index: int | None,
    expected_chunk_count: int | None,
    expected_file_count: int | None,
    filename_replacements: str | None,
    current_user: User,
    session: AsyncSession,
) -> DocumentBatchResponse:
    uploaded_files, receipt_tokens = validated_distribution_upload_inputs(
        document_type,
        upload_id,
        chunk_id,
        files,
        staging_receipts,
    )

    incoming_file_count = len(receipt_tokens) if receipt_tokens else len(uploaded_files)

    chunk_metadata = resolve_document_chunk_metadata(
        upload_id=upload_id,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        expected_chunk_count=expected_chunk_count,
        expected_file_count=expected_file_count,
    )

    validate_document_chunk_size(chunk_metadata, file_count=incoming_file_count)

    if receipt_tokens and chunk_metadata is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verified staging receipts require an upload session",
        )

    if receipt_tokens:
        validate_staging_receipt_batch(receipt_tokens, validate_verification_receipt_token_batch)

    scope = await authorize_distribution_upload(
        session=session,
        current_user=current_user,
        group_id=group_id,
        document_type=document_type,
        chunk_metadata=chunk_metadata,
    )
    agency_id = scope.agency_id
    passengers = scope.passengers
    matcher = scope.matcher
    linked_source = scope.linked_source
    supplemental_identifiers = scope.supplemental_identifiers
    roster_fingerprint = scope.roster_fingerprint
    source_fingerprint = scope.source_fingerprint
    identifiers_fingerprint = scope.identifiers_fingerprint

    content = await prepare_distribution_upload_content(
        uploaded_files=uploaded_files,
        receipt_tokens=receipt_tokens,
        chunk_metadata=chunk_metadata,
        agency_id=agency_id,
        current_user=current_user,
        group_id=group_id,
        document_type=document_type,
        roster_fingerprint=roster_fingerprint,
        source_fingerprint=source_fingerprint,
        identifiers_fingerprint=identifiers_fingerprint,
    )
    chunk_byte_count = content.chunk_byte_count
    fingerprint = content.fingerprint
    file_payloads = content.file_payloads
    preclassified_documents = content.preclassified_documents
    staged_storage_keys = content.staged_storage_keys

    replacement_decisions = parse_filename_replacements(
        filename_replacements,
        incoming_filenames=[file.filename for file in file_payloads],
    )

    fingerprint = replacement_chunk_fingerprint(fingerprint, replacement_decisions)

    replacement_cleanup_ids: list[uuid.UUID] = []
    replacement_actor_id = current_user.id
    replacement_actor_email = current_user.email

    async def cleanup_request_staging() -> None:
        await _cleanup_remembered_request_staging()

    chunk_state = await read_distribution_upload_chunk(
        session=session,
        group_id=group_id,
        agency_id=agency_id,
        document_type=document_type,
        chunk_metadata=chunk_metadata,
        incoming_file_count=incoming_file_count,
        chunk_byte_count=chunk_byte_count,
        fingerprint=fingerprint,
        passengers=passengers,
    )
    if chunk_state.replay_response is not None:
        return chunk_state.replay_response
    existing_batch = chunk_state.existing_batch
    chunk_completes_upload = chunk_state.chunk_completes_upload

    roster_snapshot = _document_match_roster_snapshot(passengers)

    if existing_batch is not None:
        # Keep the already-loaded cumulative counters available without
        # retaining a database transaction during untrusted PDF parsing.
        _detach_distribution_batch_before_long_processing(session, existing_batch)

    await session.rollback()

    persistence = DistributionUploadPersistence(
        session=session,
        current_user=current_user,
        group_id=group_id,
        agency_id=agency_id,
        document_type=document_type,
        matcher=matcher,
        roster_snapshot=roster_snapshot,
        linked_source=linked_source,
        supplemental_identifiers=supplemental_identifiers,
        chunk_metadata=chunk_metadata,
        existing_batch=existing_batch,
        fingerprint=fingerprint,
        incoming_file_count=incoming_file_count,
        chunk_byte_count=chunk_byte_count,
        replacement_decisions=replacement_decisions,
        replacement_actor_id=replacement_actor_id,
        replacement_actor_email=replacement_actor_email,
        replacement_cleanup_ids=replacement_cleanup_ids,
    )

    try:
        ingestion = await TravelDocumentIngestionService(session, matcher=matcher).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type=document_type,
            passengers=passengers,
            files=file_payloads,
            created_by_user_id=current_user.id,
            actor_email=current_user.email,
            existing_batch=existing_batch,
            batch_id=chunk_metadata.upload_id if chunk_metadata else None,
            supplemental_identifiers=supplemental_identifiers,
            isolate_pdf_parsing=True,
            parser_batch_timeout_seconds=(
                bounded_pdf_batch_timeout_seconds(incoming_file_count)
                if chunk_metadata is not None
                else None
            ),
            reject_common_unsupported_format=True,
            preclassified_documents=preclassified_documents,
            staged_storage_keys=staged_storage_keys,
            require_passenger_match=True,
            before_persistence=persistence.reauthorize_before_persistence,
            before_persistence_capacity=persistence.enforce_capacity_before_persistence,
            before_persistence_documents=persistence.replace_successfully_stored_documents,
        )
    except UnsupportedDocumentBatchFormatError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except _ConcurrentDocumentChunkReplay:
        await finish_cleanup_despite_cancellation(cleanup_request_staging())
        assert chunk_metadata is not None
        replay_batch_result = await session.execute(
            select(DocumentDistributionBatchModel).where(
                DocumentDistributionBatchModel.id == chunk_metadata.upload_id,
                DocumentDistributionBatchModel.agency_id == agency_id,
                DocumentDistributionBatchModel.group_id == group_id,
                DocumentDistributionBatchModel.document_type == document_type,
            )
        )
        replay_batch = replay_batch_result.scalar_one_or_none()
        if replay_batch is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The committed upload session is no longer available",
            )
        if replay_batch.status == "processing":
            return _processing_batch_response(replay_batch)
        documents = await _all_group_documents(
            session,
            group_id=group_id,
            agency_id=agency_id,
            document_type=document_type,
        )
        return await _batch_response(
            session=session,
            group_id=group_id,
            agency_id=agency_id,
            document_type=document_type,
            passengers=passengers,
            batch=replay_batch,
            documents=documents,
        )
    except DocumentParserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
    except DocumentDistributionCapacityError as exc:
        await finish_cleanup_despite_cancellation(cleanup_request_staging())
        raise HTTPException(
            status_code=413,
            detail=str(exc),
        ) from exc

    await commit_distribution_upload(
        session=session,
        ingestion=ingestion,
        chunk_metadata=chunk_metadata,
        chunk_completes_upload=chunk_completes_upload,
        agency_id=agency_id,
        group_id=group_id,
        document_type=document_type,
        fingerprint=fingerprint,
        incoming_file_count=incoming_file_count,
        chunk_byte_count=chunk_byte_count,
        replacement_cleanup_ids=persistence.replacement_cleanup_ids,
    )

    return await completed_distribution_upload_response(
        session=session,
        agency_id=agency_id,
        group_id=group_id,
        document_type=document_type,
        passengers=passengers,
        ingestion=ingestion,
        chunk_metadata=chunk_metadata,
    )
