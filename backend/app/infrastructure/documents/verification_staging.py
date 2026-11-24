"""Durable storage staging and compatible verification-receipt exports."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.core.logging.logger import get_logger
from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES
from app.infrastructure.documents.document_matcher import ClassifiedDocument as ClassifiedDocument
from app.infrastructure.documents.storage_cleanup import persist_storage_cleanup_job
from app.infrastructure.documents.storage_transfers import (
    finish_cleanup_despite_cancellation,
    run_bounded_storage_operations,
)
from app.infrastructure.documents.verification_receipt_cipher import (
    VerificationReceiptCipher as VerificationReceiptCipher,
)
from app.infrastructure.documents.verification_receipt_cipher import (
    _verification_receipt_fernet as _verification_receipt_fernet,
)
from app.infrastructure.documents.verification_receipt_models import (
    _SHA256_PATTERN as _SHA256_PATTERN,
)
from app.infrastructure.documents.verification_receipt_models import (
    MAX_VERIFICATION_RECEIPT_BATCH_BYTES as MAX_VERIFICATION_RECEIPT_BATCH_BYTES,
)
from app.infrastructure.documents.verification_receipt_models import (
    MAX_VERIFICATION_RECEIPT_DECODED_BATCH_BYTES as MAX_VERIFICATION_RECEIPT_DECODED_BATCH_BYTES,
)
from app.infrastructure.documents.verification_receipt_models import (
    MAX_VERIFICATION_RECEIPT_LENGTH as MAX_VERIFICATION_RECEIPT_LENGTH,
)
from app.infrastructure.documents.verification_receipt_models import (
    MAX_VERIFICATION_RECEIPT_PAYLOAD as MAX_VERIFICATION_RECEIPT_PAYLOAD,
)
from app.infrastructure.documents.verification_receipt_models import (
    VERIFICATION_RECEIPT_TTL as VERIFICATION_RECEIPT_TTL,
)
from app.infrastructure.documents.verification_receipt_models import (
    VERIFICATION_RECEIPT_VERSION as VERIFICATION_RECEIPT_VERSION,
)
from app.infrastructure.documents.verification_receipt_models import (
    VERIFICATION_STAGING_PREFIX as VERIFICATION_STAGING_PREFIX,
)
from app.infrastructure.documents.verification_receipt_models import (
    StagedDocumentReceipt as StagedDocumentReceipt,
)
from app.infrastructure.documents.verification_receipt_models import (
    VerificationReceiptBatchTooLargeError as VerificationReceiptBatchTooLargeError,
)
from app.infrastructure.documents.verification_receipt_models import (
    VerificationReceiptError as VerificationReceiptError,
)
from app.infrastructure.documents.verification_receipt_models import (
    VerificationReceiptExpiredError as VerificationReceiptExpiredError,
)
from app.infrastructure.documents.verification_receipt_models import (
    VerificationReceiptScopeChangedError as VerificationReceiptScopeChangedError,
)
from app.infrastructure.documents.verification_receipt_models import (
    VerificationStagingInput as VerificationStagingInput,
)
from app.infrastructure.documents.verification_receipt_payload import (
    _optional_string as _optional_string,
)
from app.infrastructure.documents.verification_receipt_payload import (
    _receipt_from_payload as _receipt_from_payload,
)
from app.infrastructure.documents.verification_receipt_payload import (
    _receipt_payload as _receipt_payload,
)
from app.infrastructure.documents.verification_receipt_payload import (
    _serialized_receipt_payload as _serialized_receipt_payload,
)
from app.infrastructure.documents.verification_receipt_scope import (
    _scope_fingerprint as _scope_fingerprint,
)
from app.infrastructure.documents.verification_receipt_scope import (
    _staging_storage_key as _staging_storage_key,
)
from app.infrastructure.documents.verification_receipt_scope import (
    decode_verification_receipts as decode_verification_receipts,
)
from app.infrastructure.documents.verification_receipt_scope import (
    staged_document_chunk_fingerprint as staged_document_chunk_fingerprint,
)
from app.infrastructure.documents.verification_receipt_scope import (
    validate_verification_receipt_token_batch as validate_verification_receipt_token_batch,
)
from app.infrastructure.documents.verification_receipt_scope import (
    verification_scope_fingerprints as verification_scope_fingerprints,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository

logger = get_logger("app.infrastructure.documents.verification_staging")


async def stage_verified_documents(
    inputs: list[VerificationStagingInput],
    *,
    agency_id: uuid.UUID,
    actor_id: uuid.UUID,
    group_id: uuid.UUID,
    upload_id: uuid.UUID,
    chunk_id: uuid.UUID,
    document_type: str,
    roster_fingerprint: str,
    source_fingerprint: str,
    identifiers_fingerprint: str,
    storage: MinioStorageRepository | None = None,
    cipher: VerificationReceiptCipher | None = None,
    now: datetime | None = None,
) -> list[str] | None:
    """Stage accepted PDFs and return aligned opaque receipts.

    ``None`` is a safe compatibility fallback when extracted text is too large
    for bounded form receipts; callers keep the legacy multipart upload path.
    """

    if not inputs:
        return []
    if document_type not in DOCUMENT_TYPES or any(
        not item.classification.accepted for item in inputs
    ):
        raise ValueError("Only accepted travel documents can be staged")
    timestamp = (now or datetime.now(tz=UTC)).replace(microsecond=0)
    expires_at = timestamp + VERIFICATION_RECEIPT_TTL
    active_cipher = cipher or VerificationReceiptCipher()
    receipts: list[StagedDocumentReceipt] = []
    tokens: list[str] = []
    decoded_payload_bytes = 0
    for item in inputs:
        receipt_id = uuid.uuid4()
        storage_key = _staging_storage_key(
            agency_id=agency_id,
            actor_id=actor_id,
            receipt_id=receipt_id,
        )
        receipt = StagedDocumentReceipt(
            receipt_id=receipt_id,
            agency_id=agency_id,
            actor_id=actor_id,
            group_id=group_id,
            upload_id=upload_id,
            chunk_id=chunk_id,
            document_type=document_type,
            expires_at=expires_at,
            storage_key=storage_key,
            filename=item.filename,
            content_type=item.content_type or "application/pdf",
            byte_count=len(item.content),
            content_sha256=hashlib.sha256(item.content).hexdigest(),
            roster_fingerprint=roster_fingerprint,
            source_fingerprint=source_fingerprint,
            identifiers_fingerprint=identifiers_fingerprint,
            classification=item.classification,
        )
        receipt_payload_bytes = len(_serialized_receipt_payload(receipt))
        decoded_payload_bytes += receipt_payload_bytes
        if (
            receipt_payload_bytes > MAX_VERIFICATION_RECEIPT_PAYLOAD
            or decoded_payload_bytes > MAX_VERIFICATION_RECEIPT_DECODED_BATCH_BYTES
        ):
            return None
        token = active_cipher.encrypt(receipt)
        if len(token) > MAX_VERIFICATION_RECEIPT_LENGTH:
            return None
        receipts.append(receipt)
        tokens.append(token)
    if sum(len(token.encode("ascii")) for token in tokens) > MAX_VERIFICATION_RECEIPT_BATCH_BYTES:
        return None

    active_storage = storage or MinioStorageRepository()
    storage_keys = [receipt.storage_key for receipt in receipts]

    def upload_operation(
        item: VerificationStagingInput, receipt: StagedDocumentReceipt
    ) -> Callable[[], Awaitable[str]]:
        return lambda: active_storage.upload_file(
            item.content,
            receipt.storage_key,
            item.content_type or "application/pdf",
        )

    async def cleanup() -> None:
        try:
            await active_storage.delete_files(storage_keys)
        except Exception as exc:
            logger.error(
                "document_verification_staging_cleanup_failed",
                object_count=len(storage_keys),
                error_type=type(exc).__name__,
            )

    try:
        # Commit the encrypted tombstone before the first object write so a
        # process exit cannot strand sensitive staging bytes between storage
        # upload and cleanup-job persistence. Missing-object deletion is
        # idempotent, so this also safely covers partial uploads and eager
        # finalize cleanup.
        await persist_storage_cleanup_job(
            agency_id=agency_id,
            source="document_verification_staging",
            context_id=str(receipts[0].receipt_id),
            storage_keys=storage_keys,
            not_before=expires_at,
        )
        await run_bounded_storage_operations(
            [
                upload_operation(item, receipt)
                for item, receipt in zip(inputs, receipts, strict=True)
            ]
        )
    except BaseException:
        await finish_cleanup_despite_cancellation(cleanup())
        raise
    return tokens


async def cleanup_staged_storage_keys(
    storage_keys: list[str] | tuple[str, ...],
    *,
    storage: MinioStorageRepository | None = None,
) -> None:
    keys = list(dict.fromkeys(storage_keys))
    if not keys:
        return
    if any(not key.startswith(f"{VERIFICATION_STAGING_PREFIX}/") for key in keys):
        raise ValueError("Staging cleanup keys are outside the verification namespace")
    try:
        await (storage or MinioStorageRepository()).delete_files(keys)
    except Exception as exc:
        # A durable, encrypted tombstone was committed when staging succeeded.
        logger.warning(
            "document_verification_staging_eager_cleanup_deferred",
            object_count=len(keys),
            error_type=type(exc).__name__,
        )


stage_verified_documents.__module__ = "app.infrastructure.documents.verification_staging"


cleanup_staged_storage_keys.__module__ = "app.infrastructure.documents.verification_staging"
