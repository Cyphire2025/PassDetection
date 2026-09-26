"""Validate raw and staged document upload inputs."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import HTTPException, UploadFile, status

from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES
from app.infrastructure.documents.verification_staging import (
    VerificationReceiptBatchTooLargeError,
    VerificationReceiptError,
)


def validated_distribution_upload_inputs(
    document_type: str, upload_id: uuid.UUID | None, chunk_id: uuid.UUID | None,
    files: list[UploadFile] | None, staging_receipts: list[str] | None,
) -> tuple[list[UploadFile], list[str]]:
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
    return uploaded_files, receipt_tokens


def validate_staging_receipt_batch(
    receipt_tokens: list[str], validator: Callable[[list[str]], None],
) -> None:
    try:
        validator(receipt_tokens)
    except VerificationReceiptBatchTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except VerificationReceiptError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
