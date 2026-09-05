"""Document distribution: upload."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES
from app.infrastructure.database.models import (
    DocumentDistributionBatchModel,
    DocumentUploadChunkModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.distribution_capacity import DocumentDistributionCapacityError
from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentFile,
    TravelDocumentIngestionService,
)
from app.infrastructure.documents.document_matcher import (
    ClassifiedDocument,
    DocumentMatcher,
    DocumentParserUnavailableError,
    UnsupportedDocumentBatchFormatError,
)
from app.infrastructure.documents.pdf_parser_sandbox import bounded_pdf_batch_timeout_seconds
from app.infrastructure.documents.storage_transfers import finish_cleanup_despite_cancellation
from app.infrastructure.documents.verification_staging import (
    StagedDocumentReceipt,
    VerificationReceiptBatchTooLargeError,
    VerificationReceiptError,
    VerificationReceiptExpiredError,
    VerificationReceiptScopeChangedError,
    decode_verification_receipts,
    staged_document_chunk_fingerprint,
    validate_verification_receipt_token_batch,
    verification_scope_fingerprints,
)
from app.infrastructure.security.upload_security import UploadSecurityContext
from app.presentation.api.v1.document_chunk_uploads import (
    acquire_document_upload_advisory_lock,
    acquire_document_upload_scope_advisory_lock,
    document_chunk_fingerprint,
    new_document_chunk_receipt,
    resolve_concurrent_document_chunk_replay,
    resolve_document_chunk_metadata,
    validate_document_chunk_size,
    validate_existing_document_chunk,
    validate_next_document_chunk,
)
from app.presentation.api.v1.document_uploads import (
    MAX_DOCUMENT_BATCH_BYTES,
    read_bounded_document_uploads,
)
from app.presentation.api.v1.routes.document_distribution_matching import (
    _linked_document_match_identifiers,
    _read_linked_document_match_source,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _all_group_documents,
    _enforce_group_document_assignment_capacity,
    _first_blocking_processing_upload_id,
)
from app.presentation.api.v1.routes.document_distribution_responses import _batch_response
from app.presentation.api.v1.routes.document_distribution_scope import (
    _detach_distribution_batch_before_long_processing,
    _get_authorized_group,
    _group_passengers,
    _lock_and_validate_document_match_scope,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_match_roster_snapshot,
    _processing_batch_response,
    logger,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _cleanup_distribution_storage_keys,
    _cleanup_remembered_request_staging,
    _ConcurrentDocumentChunkReplay,
    _remember_request_staging_keys,
    _with_staging_cleanup,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentBatchResponse,
    RejectedDocumentResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/groups/{group_id}/{document_type}/upload",
    response_model=DocumentBatchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
@_with_staging_cleanup
async def upload_documents(
    group_id: uuid.UUID,
    document_type: str,
    files: Annotated[list[UploadFile] | None, File()] = None,
    staging_receipts: Annotated[list[str] | None, Form()] = None,
    upload_id: Annotated[uuid.UUID | None, Form()] = None,
    chunk_id: Annotated[uuid.UUID | None, Form()] = None,
    chunk_index: Annotated[int | None, Form()] = None,
    expected_chunk_count: Annotated[int | None, Form()] = None,
    expected_file_count: Annotated[int | None, Form()] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type"
        )
    if (upload_id is None) != (chunk_id is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document verification session metadata is incomplete",
        )
    uploaded_files = files or []
    receipt_tokens = [token for token in (staging_receipts or []) if token]
    if (not uploaded_files and not receipt_tokens) or (uploaded_files and receipt_tokens):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload PDFs or verified staging receipts, but not both",
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
        try:
            validate_verification_receipt_token_batch(receipt_tokens)
        except VerificationReceiptBatchTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except VerificationReceiptError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
    authorized_group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    if chunk_metadata is not None and chunk_metadata.chunk_index == 0:
        blocking_upload_id = await _first_blocking_processing_upload_id(
            session,
            group_id=group_id,
            agency_id=authorized_group.agency_id,
            document_type=document_type,
            exclude_upload_id=chunk_metadata.upload_id,
        )
        if blocking_upload_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Discard or resume the existing incomplete upload before starting another one"
                ),
            )
    initial_passengers = await _group_passengers(
        group_id,
        current_user=current_user,
        session=session,
    )
    if not initial_passengers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This group has no passengers to match documents against",
        )
    matcher = DocumentMatcher()
    group = authorized_group
    passengers = initial_passengers
    linked_source = await _read_linked_document_match_source(
        session,
        group=group,
        lock=False,
    )
    supplemental_identifiers = await _linked_document_match_identifiers(
        session,
        group=group,
        passengers=passengers,
        matcher=matcher,
        source=linked_source,
    )
    agency_id = group.agency_id
    roster_fingerprint, source_fingerprint, identifiers_fingerprint = (
        verification_scope_fingerprints(
            roster_snapshot=_document_match_roster_snapshot(passengers),
            source_snapshot=linked_source.snapshot,
            identifiers=supplemental_identifiers,
        )
    )
    await session.rollback()

    staged_receipt_models: list[StagedDocumentReceipt] = []
    preclassified_documents: list[ClassifiedDocument] | None = None
    staged_storage_keys: list[str | None] | None = None
    if receipt_tokens:
        assert chunk_metadata is not None
        try:
            staged_receipt_models = decode_verification_receipts(
                receipt_tokens,
                agency_id=agency_id,
                actor_id=current_user.id,
                group_id=group_id,
                upload_id=chunk_metadata.upload_id,
                chunk_id=chunk_metadata.chunk_id,
                document_type=document_type,
                roster_fingerprint=roster_fingerprint,
                source_fingerprint=source_fingerprint,
                identifiers_fingerprint=identifiers_fingerprint,
            )
        except (VerificationReceiptExpiredError, VerificationReceiptScopeChangedError) as exc:
            _remember_request_staging_keys(exc.storage_keys)
            await finish_cleanup_despite_cancellation(_cleanup_remembered_request_staging())
            raise HTTPException(
                status_code=(
                    status.HTTP_410_GONE
                    if isinstance(exc, VerificationReceiptExpiredError)
                    else status.HTTP_409_CONFLICT
                ),
                detail=str(exc),
            ) from exc
        except VerificationReceiptBatchTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except VerificationReceiptError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        chunk_byte_count = sum(receipt.byte_count for receipt in staged_receipt_models)
        _remember_request_staging_keys([receipt.storage_key for receipt in staged_receipt_models])
        per_file_limit = get_settings().upload_max_file_size_bytes
        if chunk_byte_count > MAX_DOCUMENT_BATCH_BYTES or any(
            receipt.byte_count > per_file_limit for receipt in staged_receipt_models
        ):
            await finish_cleanup_despite_cancellation(_cleanup_remembered_request_staging())
            raise HTTPException(
                status_code=413,
                detail="The verified PDF upload exceeds the active size limit",
            )
        fingerprint = (
            staged_document_chunk_fingerprint(staged_receipt_models) if chunk_metadata else None
        )
        file_payloads = [
            TravelDocumentFile(
                filename=receipt.filename,
                content=b"",
                content_type=receipt.content_type,
            )
            for receipt in staged_receipt_models
        ]
        preclassified_documents = [receipt.classification for receipt in staged_receipt_models]
        staged_storage_keys = [receipt.storage_key for receipt in staged_receipt_models]
    else:
        uploads = await read_bounded_document_uploads(
            uploaded_files,
            security_context=UploadSecurityContext(
                ingestion_flow="document_distribution_upload",
                agency_id=agency_id,
                user_id=current_user.id,
            ),
        )
        chunk_byte_count = sum(len(upload.content) for upload in uploads)
        fingerprint = document_chunk_fingerprint(uploads) if chunk_metadata else None
        file_payloads = [
            TravelDocumentFile(
                filename=upload.filename,
                content=upload.content,
                content_type=upload.content_type,
            )
            for upload in uploads
        ]

    async def cleanup_request_staging() -> None:
        await _cleanup_remembered_request_staging()

    existing_batch: DocumentDistributionBatchModel | None = None
    existing_receipts: list[DocumentUploadChunkModel] = []
    chunk_completes_upload = True
    if chunk_metadata is not None:
        batch_result = await session.execute(
            select(DocumentDistributionBatchModel).where(
                DocumentDistributionBatchModel.id == chunk_metadata.upload_id,
                DocumentDistributionBatchModel.agency_id == agency_id,
                DocumentDistributionBatchModel.group_id == group_id,
                DocumentDistributionBatchModel.document_type == document_type,
            )
        )
        existing_batch = batch_result.scalar_one_or_none()
        if existing_batch is None:
            collision_result = await session.execute(
                select(DocumentDistributionBatchModel.id).where(
                    DocumentDistributionBatchModel.id == chunk_metadata.upload_id
                )
            )
            if collision_result.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is not available to this group",
                )
        receipt_result = await session.execute(
            select(DocumentUploadChunkModel).where(
                DocumentUploadChunkModel.id == chunk_metadata.chunk_id
            )
        )
        existing_receipt = receipt_result.scalar_one_or_none()
        if existing_receipt is not None:
            assert fingerprint is not None
            validate_existing_document_chunk(
                existing_receipt,
                metadata=chunk_metadata,
                agency_id=agency_id,
                workflow="distribution",
                group_id=group_id,
                document_type=document_type,
                fingerprint=fingerprint,
                file_count=incoming_file_count,
                byte_count=chunk_byte_count,
            )
            if existing_batch is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is not available to this group",
                )
            if existing_batch.status == "processing":
                await finish_cleanup_despite_cancellation(cleanup_request_staging())
                return _processing_batch_response(existing_batch)
            documents = await _all_group_documents(
                session,
                group_id=group_id,
                agency_id=agency_id,
                document_type=document_type,
            )
            replay_response = await _batch_response(
                session=session,
                group_id=group_id,
                agency_id=agency_id,
                document_type=document_type,
                passengers=passengers,
                batch=existing_batch,
                documents=documents,
            )
            await finish_cleanup_despite_cancellation(cleanup_request_staging())
            return replay_response
        receipts_result = await session.execute(
            select(DocumentUploadChunkModel)
            .where(
                DocumentUploadChunkModel.upload_id == chunk_metadata.upload_id,
                DocumentUploadChunkModel.agency_id == agency_id,
                DocumentUploadChunkModel.workflow == "distribution",
                DocumentUploadChunkModel.group_id == group_id,
                DocumentUploadChunkModel.document_type == document_type,
            )
            .order_by(DocumentUploadChunkModel.chunk_index.asc())
        )
        existing_receipts = list(receipts_result.scalars().all())
        if (existing_batch is None) != (len(existing_receipts) == 0):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The upload session is incomplete and requires administrator review",
            )
        if existing_batch is not None and existing_batch.status != "processing":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This upload session is already complete",
            )
        chunk_completes_upload = validate_next_document_chunk(
            existing_receipts,
            metadata=chunk_metadata,
            incoming_file_count=incoming_file_count,
            incoming_byte_count=chunk_byte_count,
        )
    roster_snapshot = _document_match_roster_snapshot(passengers)
    if existing_batch is not None:
        # Keep the already-loaded cumulative counters available without
        # retaining a database transaction during untrusted PDF parsing.
        _detach_distribution_batch_before_long_processing(session, existing_batch)
    await session.rollback()

    async def reauthorize_before_persistence() -> tuple[uuid.UUID | None, str | None]:
        actor, _ = await _lock_and_validate_document_match_scope(
            session,
            current_user=current_user,
            group_id=group_id,
            agency_id=agency_id,
            matcher=matcher,
            expected_roster_snapshot=roster_snapshot,
            expected_source_snapshot=linked_source.snapshot,
            expected_supplemental_identifiers=supplemental_identifiers,
        )
        await acquire_document_upload_scope_advisory_lock(
            session,
            agency_id=agency_id,
            group_id=group_id,
            document_type=document_type,
        )
        if chunk_metadata is not None:
            await acquire_document_upload_advisory_lock(
                session,
                workflow="distribution",
                upload_id=chunk_metadata.upload_id,
            )
            serialized_batch_result = await session.execute(
                select(DocumentDistributionBatchModel)
                .where(DocumentDistributionBatchModel.id == chunk_metadata.upload_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            serialized_batch = serialized_batch_result.scalar_one_or_none()
            if serialized_batch is not None and (
                serialized_batch.agency_id != agency_id
                or serialized_batch.group_id != group_id
                or serialized_batch.document_type != document_type
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is not available to this group",
                )
            if (
                chunk_metadata.chunk_index == 0
                and serialized_batch is None
                and await _first_blocking_processing_upload_id(
                    session,
                    group_id=group_id,
                    agency_id=agency_id,
                    document_type=document_type,
                    exclude_upload_id=chunk_metadata.upload_id,
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
            locked_receipts_result = await session.execute(
                select(DocumentUploadChunkModel)
                .where(
                    DocumentUploadChunkModel.upload_id == chunk_metadata.upload_id,
                    DocumentUploadChunkModel.workflow == "distribution",
                )
                .order_by(DocumentUploadChunkModel.chunk_index.asc())
                .with_for_update()
            )
            locked_receipts = list(locked_receipts_result.scalars().all())
            assert fingerprint is not None
            if (
                resolve_concurrent_document_chunk_replay(
                    locked_receipts,
                    metadata=chunk_metadata,
                    agency_id=agency_id,
                    workflow="distribution",
                    group_id=group_id,
                    document_type=document_type,
                    fingerprint=fingerprint,
                    file_count=incoming_file_count,
                    byte_count=chunk_byte_count,
                )
                is not None
            ):
                raise _ConcurrentDocumentChunkReplay
            if serialized_batch is not None and existing_batch is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is incomplete and requires administrator review",
                )
            if serialized_batch is None and existing_batch is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is no longer available",
                )
            validate_next_document_chunk(
                locked_receipts,
                metadata=chunk_metadata,
                incoming_file_count=incoming_file_count,
                incoming_byte_count=chunk_byte_count,
            )
        return actor.id, actor.email

    async def enforce_capacity_before_persistence(incoming_rows: int) -> None:
        await _enforce_group_document_assignment_capacity(
            session,
            group_id=group_id,
            agency_id=agency_id,
            document_type=document_type,
            incoming_rows=incoming_rows,
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
            before_persistence=reauthorize_before_persistence,
            before_persistence_capacity=enforce_capacity_before_persistence,
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
    if chunk_metadata is not None:
        ingestion.batch.status = "draft" if chunk_completes_upload else "processing"
        assert fingerprint is not None
        session.add(
            new_document_chunk_receipt(
                metadata=chunk_metadata,
                agency_id=agency_id,
                workflow="distribution",
                group_id=group_id,
                document_type=document_type,
                fingerprint=fingerprint,
                file_count=incoming_file_count,
                byte_count=chunk_byte_count,
                accepted_count=incoming_file_count - len(ingestion.rejected),
                rejected_count=len(ingestion.rejected),
                rejected_documents=[
                    {
                        "filename": item.filename,
                        "detected_type": item.detected_type,
                        "reason": item.reason,
                    }
                    for item in ingestion.rejected
                ],
            )
        )
        try:
            await session.flush()
        except BaseException:
            await session.rollback()
            await _cleanup_distribution_storage_keys(
                list(ingestion.created_storage_keys),
                agency_id=agency_id,
                group_id=group_id,
                document_type=document_type,
            )
            raise
    try:
        await session.commit()
    except BaseException:
        # COMMIT acknowledgement can be lost after PostgreSQL made the rows
        # durable. Keep objects that those rows may reference for safe
        # operational reconciliation; remove only proven orphaned keys.
        await session.rollback()
        logger.warning(
            "document_distribution_commit_outcome_ambiguous",
            group_id=str(group_id),
            document_type=document_type,
            object_count=len(ingestion.created_storage_keys),
        )
        raise
    await finish_cleanup_despite_cancellation(cleanup_request_staging())
    if ingestion.batch.status == "processing":
        return _processing_batch_response(ingestion.batch)
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
        batch=ingestion.batch,
        documents=documents,
        rejected_documents=(
            [
                RejectedDocumentResponse(
                    filename=item.filename,
                    detected_type=item.detected_type,
                    reason=item.reason,
                )
                for item in ingestion.rejected
            ]
            if chunk_metadata is None
            else None
        ),
    )
