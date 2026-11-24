"""Distribution upload content."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile, status

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentFile,
)
from app.infrastructure.documents.document_matcher import (
    ClassifiedDocument,
)
from app.infrastructure.documents.storage_transfers import finish_cleanup_despite_cancellation
from app.infrastructure.documents.verification_staging import (
    StagedDocumentReceipt,
    VerificationReceiptBatchTooLargeError,
    VerificationReceiptError,
    VerificationReceiptExpiredError,
    VerificationReceiptScopeChangedError,
    decode_verification_receipts,
    staged_document_chunk_fingerprint,
)
from app.infrastructure.security.upload_security import UploadSecurityContext
from app.presentation.api.v1.document_chunk_uploads import (
    DocumentChunkMetadata,
    document_chunk_fingerprint,
)
from app.presentation.api.v1.document_uploads import (
    MAX_DOCUMENT_BATCH_BYTES,
    read_bounded_document_uploads,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _cleanup_remembered_request_staging,
    _remember_request_staging_keys,
)


@dataclass(frozen=True, slots=True)
class DistributionUploadContent:
    chunk_byte_count: int
    fingerprint: str | None
    file_payloads: list[TravelDocumentFile]
    preclassified_documents: list[ClassifiedDocument] | None
    staged_storage_keys: list[str | None] | None


async def prepare_distribution_upload_content(
    *,
    uploaded_files: list[UploadFile],
    receipt_tokens: list[str],
    chunk_metadata: DocumentChunkMetadata | None,
    agency_id: uuid.UUID,
    current_user: User,
    group_id: uuid.UUID,
    document_type: str,
    roster_fingerprint: str,
    source_fingerprint: str,
    identifiers_fingerprint: str,
) -> DistributionUploadContent:
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

    return DistributionUploadContent(
        chunk_byte_count, fingerprint, file_payloads, preclassified_documents, staged_storage_keys
    )
